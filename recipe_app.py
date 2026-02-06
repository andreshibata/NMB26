import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json
from datetime import datetime

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Sistema ERP Cozinha", layout="wide", page_icon="🏭")

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
                st.error("Erro crítico de conexão.")
                st.stop()
    return firestore.client()

db = conectar_banco()

# --- 3. FUNÇÕES DE BANCO DE DADOS ---

# --- ESTOQUE (INVENTORY) ---
def adicionar_entrada_estoque(nome, marca, mercado, preco, tamanho, unidade):
    """Adiciona itens ao armazém (Soma se já existir o mesmo lote)"""
    # ID único baseada na Marca/Mercado para diferenciar preços
    doc_id = f"{nome}_{marca}_{mercado}".replace(" ", "_").lower()
    
    ref = db.collection("inventory").document(doc_id)
    doc = ref.get()
    
    if doc.exists:
        # Se já existe esse exato item, somamos ao estoque atual
        dados_antigos = doc.to_dict()
        novo_estoque = dados_antigos['estoque_atual'] + tamanho
        # Atualizamos o preço para o mais recente (ou poderia fazer média ponderada)
        ref.update({
            "estoque_atual": novo_estoque,
            "preco_pago": preco, 
            "data_entrada": firestore.SERVER_TIMESTAMP
        })
    else:
        # Cria novo item
        ref.set({
            "nome": nome,
            "marca": marca,
            "mercado": mercado,
            "preco_pago": preco,
            "tamanho_orig": tamanho,
            "estoque_atual": tamanho,
            "unidade": unidade,
            "custo_por_unidade": preco / tamanho if tamanho > 0 else 0,
            "data_entrada": firestore.SERVER_TIMESTAMP
        })

def pegar_estoque_completo():
    docs = db.collection("inventory").stream()
    return [doc.to_dict() for doc in docs]

# --- RECEITAS (RECIPES) ---
def salvar_ficha_tecnica(nome, autor, ingredientes):
    """Salva apenas O QUE é necessário, não mexe no estoque"""
    doc_id = f"{nome}_{autor}".replace(" ", "_").lower()
    
    # Calculamos um custo estimado baseado nos ingredientes inseridos na hora da criação
    custo_estimado = sum(i['custo_estimado'] for i in ingredientes)
    
    db.collection("recipes").document(doc_id).set({
        "name": nome,
        "author": autor,
        "ingredients": ingredientes,
        "estimated_cost": custo_estimado,
        "created_at": firestore.SERVER_TIMESTAMP
    })

def pegar_receitas():
    docs = db.collection("recipes").stream()
    return [doc.to_dict() for doc in docs]

# --- PRODUÇÃO E HISTÓRICO ---
def registrar_producao(nome_receita, qtd_produzida, ingredientes_receita):
    """
    1. Verifica estoque
    2. Deduz estoque
    3. Salva no histórico
    """
    log_erros = []
    log_sucesso = []
    custo_real_producao = 0
    
    estoque_atual = pegar_estoque_completo()
    
    # VERIFICAÇÃO E BAIXA
    # Agrupamos as baixas para garantir que temos tudo antes de começar? 
    # Para simplificar, vamos tentar baixar item a item.
    
    for item in ingredientes_receita:
        nome_necessario = item['nome']
        qtd_total_necessaria = item['qtd_usada'] * qtd_produzida
        
        # Busca lotes disponíveis desse ingrediente
        lotes = [e for e in estoque_atual if e['nome'] == nome_necessario and e['estoque_atual'] > 0]
        
        # Ordena para usar primeiro os que tem menos estoque (ou mais antigos se tivesse data)
        lotes.sort(key=lambda x: x['estoque_atual'])
        
        qtd_pendente = qtd_total_necessaria
        
        if sum(l['estoque_atual'] for l in lotes) < qtd_pendente:
            log_erros.append(f"❌ Falta Estoque de {nome_necessario}. Precisa: {qtd_pendente}")
            continue # Pula a baixa desse item mas avisa erro
            
        for lote in lotes:
            if qtd_pendente <= 0: break
            
            doc_id = f"{lote['nome']}_{lote['marca']}_{lote['mercado']}".replace(" ", "_").lower()
            
            # Quanto custou esse pedacinho que estamos usando?
            custo_lote_unit = lote['custo_por_unidade']
            
            if lote['estoque_atual'] >= qtd_pendente:
                # Lote aguenta tudo
                usado = qtd_pendente
                novo_saldo = lote['estoque_atual'] - qtd_pendente
                db.collection("inventory").document(doc_id).update({"estoque_atual": novo_saldo})
                qtd_pendente = 0
            else:
                # Lote acaba
                usado = lote['estoque_atual']
                db.collection("inventory").document(doc_id).update({"estoque_atual": 0})
                qtd_pendente -= usado
            
            custo_real_producao += (usado * custo_lote_unit)
            
    if log_erros:
        return False, log_erros
    
    # SE DEU TUDO CERTO, SALVA NO HISTÓRICO
    db.collection("history").add({
        "receita": nome_receita,
        "quantidade": qtd_produzida,
        "custo_total_real": custo_real_producao,
        "data": firestore.SERVER_TIMESTAMP
    })
    
    return True, [f"Produção de {qtd_produzida}x {nome_receita} realizada com sucesso! Custo Real: R$ {custo_real_producao:.2f}"]

def pegar_historico():
    # Pega os ultimos 20 registros
    docs = db.collection("history").order_by("data", direction=firestore.Query.DESCENDING).limit(20).stream()
    return [doc.to_dict() for doc in docs]

# --- 4. INTERFACE ---
st.title("🏭 Sistema de Gestão Industrial")

# Login Rápido
if st.sidebar.text_input("Senha", type="password") != st.secrets.get("senha_app", "admin"):
    st.warning("Acesso Restrito")
    st.stop()

aba_estoque, aba_receitas, aba_producao, aba_historico = st.tabs([
    "📦 1. Estoque (Compras)", 
    "📝 2. Receitas (Ficha Técnica)", 
    "⚙️ 3. Produção (Baixa)",
    "📜 4. Histórico"
])

# ==================================================
# ABA 1: ESTOQUE (ENTRADA DE MERCADORIA)
# ==================================================
with aba_estoque:
    st.header("Entrada de Nota Fiscal / Compras")
    st.caption("Adicione aqui tudo que você comprou. Isso enche o armazém.")
    
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        nome = c1.text_input("Ingrediente (Genérico)", placeholder="Ex: Leite")
        marca = c2.text_input("Marca/Detalhe", placeholder="Ex: Parmalat")
        mercado = c3.text_input("Local de Compra", placeholder="Ex: Atacadão")
        
        c4, c5, c6, c7 = st.columns(4)
        preco = c4.number_input("Preço Pago (R$)", min_value=0.0, format="%.2f")
        tamanho = c5.number_input("Tamanho Pacote", min_value=0.0)
        unidade = c6.selectbox("Unidade", ["g", "ml", "unid", "kg", "L"])
        
        if c7.button("📥 Dar Entrada", type="primary"):
            if nome and tamanho > 0:
                adicionar_entrada_estoque(nome, marca, mercado, preco, tamanho, unidade)
                st.success(f"Estoque de {nome} atualizado!")
                st.rerun()
            else:
                st.error("Preencha Nome e Tamanho.")

    st.divider()
    st.subheader("Estoque Atual")
    items = pegar_estoque_completo()
    if items:
        # Filtra só o que tem saldo
        ativos = [i for i in items if i['estoque_atual'] > 0]
        st.dataframe(
            pd.DataFrame(ativos)[["nome", "marca", "estoque_atual", "unidade", "mercado"]], 
            use_container_width=True
        )
    else:
        st.info("Estoque vazio.")

# ==================================================
# ABA 2: RECEITAS (APENAS MODELO)
# ==================================================
with aba_receitas:
    st.header("Criar Ficha Técnica")
    st.caption("Defina COMO se faz. Isso não altera o estoque agora.")
    
    if 'temp_ing' not in st.session_state:
        st.session_state.temp_ing = []
        
    # Formulário de Adição
    with st.container(border=True):
        st.write("Adicionar Ingrediente à Receita")
        # Dropdown inteligente que puxa nomes do estoque pra facilitar digitação
        nomes_estoque = sorted(list(set([i['nome'] for i in pegar_estoque_completo()])))
        
        cc1, cc2, cc3 = st.columns([2, 1, 1])
        
        modo = cc1.radio("Fonte", ["Do Estoque", "Manual"], horizontal=True, label_visibility="collapsed")
        if modo == "Do Estoque" and nomes_estoque:
            sel_nome = cc1.selectbox("Selecione", nomes_estoque)
        else:
            sel_nome = cc1.text_input("Nome do Ingrediente")
            
        qtd_nec = cc2.number_input("Qtd Necessária", min_value=0.0)
        unid_rec = cc3.selectbox("Unid", ["g", "ml", "unid", "kg", "L"], key="u_rec")
        
        if st.button("Adicionar à Lista"):
            if sel_nome and qtd_nec > 0:
                # Estimativa de custo (opcional, pega o primeiro do estoque pra ter nocao)
                custo_est = 0
                st.session_state.temp_ing.append({
                    "nome": sel_nome,
                    "qtd_usada": qtd_nec,
                    "unidade": unid_rec,
                    "custo_estimado": 0 # Pode ser calculado depois
                })
                
    # Lista Temporária
    if st.session_state.temp_ing:
        st.dataframe(pd.DataFrame(st.session_state.temp_ing), use_container_width=True)
        
        with st.form("save_rec_form"):
            r_nome = st.text_input("Nome da Receita")
            r_autor = st.text_input("Autor")
            if st.form_submit_button("💾 Salvar Ficha Técnica"):
                salvar_ficha_tecnica(r_nome, r_autor, st.session_state.temp_ing)
                st.success("Receita cadastrada!")
                st.session_state.temp_ing = []
                st.rerun()

# ==================================================
# ABA 3: PRODUÇÃO (BAIXA DE ESTOQUE)
# ==================================================
with aba_producao:
    st.header("Ordem de Produção")
    st.caption("Aqui você diz o que produziu. O sistema desconta do estoque.")
    
    receitas = pegar_receitas()
    
    if receitas:
        sel_rec = st.selectbox("Selecione a Receita", [r['name'] for r in receitas])
        qtd_prod = st.number_input("Quantidade Produzida", min_value=1, value=1)
        
        dados_rec = next(r for r in receitas if r['name'] == sel_rec)
        
        # Simulação (Preview)
        st.write("---")
        st.subheader("Pré-visualização de Materiais")
        
        falta_material = False
        estoque_atual = pegar_estoque_completo()
        preview = []
        
        for ing in dados_rec['ingredients']:
            total_nec = ing['qtd_usada'] * qtd_prod
            # Soma estoque de todas as marcas desse produto
            total_disp = sum(e['estoque_atual'] for e in estoque_atual if e['nome'] == ing['nome'])
            
            status = "✅ OK" if total_disp >= total_nec else "❌ FALTA"
            if total_disp < total_nec: falta_material = True
            
            preview.append({
                "Ingrediente": ing['nome'],
                "Necessário": total_nec,
                "Em Estoque": total_disp,
                "Status": status
            })
            
        st.dataframe(pd.DataFrame(preview), use_container_width=True)
        
        btn_disable = falta_material
        if btn_disable:
            st.error("Não é possível produzir. Estoque insuficiente.")
        
        if st.button("🚀 Confirmar Produção", type="primary", disabled=btn_disable):
            sucesso, msgs = registrar_producao(sel_rec, qtd_prod, dados_rec['ingredients'])
            if sucesso:
                st.success(msgs[0])
                st.balloons()
            else:
                st.error("Erro na baixa:")
                for m in msgs: st.write(m)

# ==================================================
# ABA 4: HISTÓRICO
# ==================================================
with aba_historico:
    st.header("Log de Produção")
    logs = pegar_historico()
    
    if logs:
        # Converter timestamp do Firebase para data legível
        dados_formatados = []
        for l in logs:
            dt = l.get('data')
            if dt:
                dt_str = dt.strftime("%d/%m/%Y %H:%M")
            else:
                dt_str = "-"
                
            dados_formatados.append({
                "Data": dt_str,
                "Receita": l['receita'],
                "Qtd Produzida": l['quantidade'],
                "Custo Real (Baixa Estoque)": f"R$ {l.get('custo_total_real', 0):.2f}"
            })
            
        st.dataframe(pd.DataFrame(dados_formatados), use_container_width=True)
    else:
        st.info("Nenhuma produção registrada ainda.")
