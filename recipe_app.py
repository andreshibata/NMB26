import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json
from datetime import datetime

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Sistema de Produção & Estoque", layout="wide", page_icon="🏭")

# --- 2. CONEXÃO SEGURA ---
@st.cache_resource
def conectar_banco():
    if not firebase_admin._apps:
        try:
            cred = credentials.Certificate("firebase_key.json") 
            firebase_admin.initialize_app(cred)
        except:
            if "textkey" in st.secrets:
                key_dict = json.loads(st.secrets["textkey"])
                cred = credentials.Certificate(key_dict)
                firebase_admin.initialize_app(cred)
            else:
                st.error("Erro de conexão com banco de dados.")
                st.stop()
    return firestore.client()

db = conectar_banco()

# --- 3. FUNÇÕES DE BANCO DE DADOS ---

def adicionar_estoque(nome, marca, mercado, preco, tamanho, unidade):
    """Adiciona um item específico ao Armazém"""
    # ID único combinando nome, marca e mercado para diferenciar versões
    safe_id = f"{nome}_{marca}_{mercado}".replace(" ", "_").lower()
    
    db.collection("inventory").document(safe_id).set({
        "nome": nome,
        "marca": marca,
        "mercado": mercado,
        "preco_pago": preco,
        "tamanho_orig": tamanho,
        "estoque_atual": tamanho, # Começa cheio
        "unidade": unidade,
        "custo_por_unidade": preco / tamanho if tamanho > 0 else 0,
        "data_compra": firestore.SERVER_TIMESTAMP
    })

def pegar_estoque():
    """Pega tudo que está no armazém"""
    docs = db.collection("inventory").stream()
    return [doc.to_dict() for doc in docs]

def salvar_receita(nome, autor, ingredientes):
    doc_id = f"{nome}_{autor}".replace(" ", "_").lower()
    # A receita salva apenas o NOME genérico do ingrediente e a quantidade necessária
    db.collection("recipes").document(doc_id).set({
        "name": nome,
        "author": autor,
        "ingredients": ingredientes,
        "created_at": firestore.SERVER_TIMESTAMP
    })

def pegar_receitas():
    docs = db.collection("recipes").stream()
    lista = []
    for doc in docs:
        d = doc.to_dict()
        d['id'] = doc.id
        lista.append(d)
    return lista

def realizar_baixa_estoque(plano_producao):
    """
    Abate do estoque os itens usados.
    plano_producao = [{'nome_ingrediente': 'Farinha', 'qtd_necessaria': 1000}, ...]
    """
    log_msg = []
    
    estoque_atual = pegar_estoque()
    
    for item_nec in plano_producao:
        nome_buscado = item_nec['nome']
        qtd_restante_para_abater = item_nec['qtd_necessaria']
        
        # Procura no estoque itens com esse nome (Ex: Farinha Dona Benta, Farinha Sol)
        # Ordena para usar primeiro o que tem menos estoque (FIFO) ou lógica preferida
        lotes_compativeis = [i for i in estoque_atual if i['nome'] == nome_buscado and i['estoque_atual'] > 0]
        
        if not lotes_compativeis:
            log_msg.append(f"❌ FALTA: {nome_buscado} (Não há estoque suficiente)")
            continue
            
        for lote in lotes_compativeis:
            if qtd_restante_para_abater <= 0:
                break
                
            safe_id = f"{lote['nome']}_{lote['marca']}_{lote['mercado']}".replace(" ", "_").lower()
            
            # Se o lote tem mais do que precisamos
            if lote['estoque_atual'] >= qtd_restante_para_abater:
                novo_estoque = lote['estoque_atual'] - qtd_restante_para_abater
                db.collection("inventory").document(safe_id).update({"estoque_atual": novo_estoque})
                log_msg.append(f"✅ Usado {qtd_restante_para_abater}{lote['unidade']} de {lote['nome']} ({lote['marca']})")
                qtd_restante_para_abater = 0
            
            # Se o lote acaba e ainda precisamos de mais
            else:
                usado = lote['estoque_atual']
                db.collection("inventory").document(safe_id).update({"estoque_atual": 0})
                qtd_restante_para_abater -= usado
                log_msg.append(f"⚠️ Lote de {lote['nome']} ({lote['marca']}) acabou! Usado: {usado}")
                
        if qtd_restante_para_abater > 0:
             log_msg.append(f"❌ ATENÇÃO: Faltou {qtd_restante_para_abater} de {nome_buscado}!")

    return log_msg

# --- 4. APP INTERFACE ---

# --- LOGIN ---
with st.sidebar:
    st.title("🏭 Controle Industrial")
    senha = st.text_input("Senha", type="password")
    if senha != st.secrets.get("senha_app", "admin"):
        st.warning("Acesso Bloqueado")
        st.stop()
    st.success("Logado")

st.title("Sistema de Gestão de Receitas & Estoque")

aba_armazem, aba_receita, aba_producao = st.tabs([
    "📦 Armazém (Entrada)", 
    "📝 Ficha Técnica (Receitas)", 
    "⚙️ Produção & Baixa"
])

# ==================================================
# ABA 1: ARMAZÉM (CADASTRO DE PRODUTOS ESPECÍFICOS)
# ==================================================
with aba_armazem:
    st.header("Entrada de Mercadoria")
    st.caption("Aqui você cadastra o produto exato que comprou (Marca, Mercado, Lote).")
    
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        nome = c1.text_input("Produto (Genérico)", placeholder="Ex: Farinha de Trigo")
        marca = c2.text_input("Marca", placeholder="Ex: Dona Benta")
        mercado = c3.text_input("Fornecedor/Mercado", placeholder="Ex: Assaí")
        
        c4, c5, c6, c7 = st.columns(4)
        preco = c4.number_input("Preço Pago (R$)", 0.0, format="%.2f")
        tamanho = c5.number_input("Tamanho da Embalagem", 0.0)
        unidade = c6.selectbox("Unidade", ["g", "ml", "unid", "kg", "L"])
        
        if c7.button("📥 Dar Entrada no Estoque", type="primary"):
            if nome and tamanho > 0:
                adicionar_estoque(nome, marca, mercado, preco, tamanho, unidade)
                st.success(f"Entrada confirmada: {nome} - {marca}")
                st.rerun()
            else:
                st.error("Preencha Nome e Tamanho")

    st.divider()
    st.subheader("Estoque Atual Disponível")
    estoque = pegar_estoque()
    if estoque:
        df_est = pd.DataFrame(estoque)
        # Mostra colunas relevantes e formata
        st.dataframe(
            df_est[["nome", "marca", "mercado", "estoque_atual", "unidade", "preco_pago"]].style.format({"preco_pago": "R$ {:.2f}", "estoque_atual": "{:.1f}"}),
            use_container_width=True
        )
    else:
        st.info("Armazém vazio.")


# ==================================================
# ABA 2: RECEITAS (GENÉRICAS)
# ==================================================
with aba_receita:
    st.header("Criar Ficha Técnica")
    st.caption("A receita usa nomes genéricos. O custo é calculado pela média do estoque.")
    
    if 'temp_rec' not in st.session_state:
        st.session_state.temp_rec = []
        
    estoque_disp = pegar_estoque()
    # Pega apenas nomes únicos para o dropdown
    nomes_unicos = sorted(list(set([i['nome'] for i in estoque_disp])))
    
    c1, c2, c3 = st.columns([2, 1, 1])
    
    if nomes_unicos:
        sel_item = c1.selectbox("Ingrediente", nomes_unicos)
        # Pega a unidade do primeiro item encontrado com esse nome só pra facilitar
        ref_unid = next(i['unidade'] for i in estoque_disp if i['nome'] == sel_item)
        
        qtd_nec = c2.number_input(f"Qtd Necessária ({ref_unid})", 0.0)
        
        if c3.button("Adicionar Item"):
            if qtd_nec > 0:
                st.session_state.temp_rec.append({
                    "nome": sel_item,
                    "qtd": qtd_nec,
                    "unidade": ref_unid
                })
    else:
        st.warning("Cadastre itens no Armazém primeiro!")

    if st.session_state.temp_rec:
        st.divider()
        st.write("### Itens da Receita:")
        st.dataframe(pd.DataFrame(st.session_state.temp_rec), use_container_width=True)
        
        with st.form("salvar_rec"):
            rn = st.text_input("Nome da Receita")
            ra = st.text_input("Autor")
            if st.form_submit_button("💾 Salvar Ficha Técnica"):
                salvar_receita(rn, ra, st.session_state.temp_rec)
                st.success("Receita Salva!")
                st.session_state.temp_rec = []
                st.rerun()

# ==================================================
# ABA 3: PLANEJAMENTO DE PRODUÇÃO (O GRANDE DIFERENCIAL)
# ==================================================
with aba_producao:
    st.header("Planejamento de Produção")
    st.caption("Simule quanto você quer produzir e o sistema verifica se tem estoque.")
    
    receitas = pegar_receitas()
    
    if receitas:
        # 1. Selecionar o que vai cozinhar
        sel_receita_nome = st.selectbox("O que vamos cozinhar hoje?", [r['name'] for r in receitas])
        dados_receita = next(r for r in receitas if r['name'] == sel_receita_nome)
        
        # 2. Quantas unidades?
        qtd_producao = st.number_input("Quantas receitas (unidades) vamos fazer?", min_value=1, value=1)
        
        st.divider()
        
        # 3. Cálculo de Necessidade
        st.subheader("📦 Materiais Necessários vs. Estoque")
        
        plano_execucao = []
        pode_produzir = True
        
        relatorio = []
        
        estoque_atual = pegar_estoque()
        
        for item in dados_receita['ingredients']:
            total_necessario = item['qtd'] * qtd_producao
            
            # Soma todo o estoque disponível para esse nome (independente da marca)
            total_em_estoque = sum(e['estoque_atual'] for e in estoque_atual if e['nome'] == item['nome'])
            
            status = "✅ OK" if total_em_estoque >= total_necessario else "❌ FALTA"
            saldo_pos_producao = total_em_estoque - total_necessario
            
            if saldo_pos_producao < 0:
                pode_produzir = False
            
            relatorio.append({
                "Ingrediente": item['nome'],
                "Necessário": total_necessario,
                "Em Estoque (Total)": total_em_estoque,
                "Sobra Prevista": saldo_pos_producao if saldo_pos_producao > 0 else 0,
                "Status": status
            })
            
            plano_execucao.append({
                "nome": item['nome'],
                "qtd_necessaria": total_necessario
            })
            
        st.dataframe(pd.DataFrame(relatorio), use_container_width=True)
        
        st.write("---")
        
        # 4. Botão de Execução Real
        c_act1, c_act2 = st.columns([3, 1])
        
        if c_act1.button("🏭 CONFIRMAR PRODUÇÃO E BAIXAR ESTOQUE", type="primary", disabled=not pode_produzir):
            log = realizar_baixa_estoque(plano_execucao)
            st.success("Produção Registrada! Estoque atualizado.")
            with st.expander("Ver Log de Baixas"):
                for linha in log:
                    st.write(linha)
                    
        if not pode_produzir:
            st.error("Não há estoque suficiente para essa produção. Compre os itens marcados com FALTA.")

    else:
        st.info("Cadastre receitas primeiro.")
