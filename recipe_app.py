import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Gestor de Receitas & Sobras", layout="wide", page_icon="🥘")

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
                st.error("❌ Erro de conexão.")
                st.stop()
    return firestore.client()

db = conectar_banco()

# --- 3. FUNÇÕES ---

def pegar_estoque():
    """Pega tudo que sobrou de outras receitas"""
    docs = db.collection("inventory").stream()
    # Retorna lista de dicionários
    return [doc.to_dict() for doc in docs]

def salvar_receita_e_atualizar_sobras(nome, autor, ingredientes, salvar_sobras=True):
    # 1. Cria ID único
    doc_id = f"{nome}_{autor}".replace(" ", "_").lower()
    custo_total = sum(i['custo_final'] for i in ingredientes)
    
    # 2. Salva a Receita
    db.collection("recipes").document(doc_id).set({
        "name": nome,
        "author": autor,
        "ingredients": ingredientes,
        "total_cost": custo_total,
        "created_at": firestore.SERVER_TIMESTAMP
    })
    
    # 3. Atualiza o Estoque com o que sobrou (SE solicitado)
    if salvar_sobras:
        for item in ingredientes:
            # Sobra = O pacote que comprei MENOS o que usei
            sobra = item['tam_pacote'] - item['qtd_usada']
            
            if sobra > 0:
                # Cria um ID específico para essa marca/ingrediente
                nome_marca = item.get('marca', 'Genérico')
                estoque_id = f"{item['nome']}_{nome_marca}".replace(" ", "_").lower()
                
                # Verifica se já existe para somar (opcional) ou sobrescreve
                # Aqui vamos somar se já existir esse mesmo item/marca
                ref = db.collection("inventory").document(estoque_id)
                doc = ref.get()
                
                if doc.exists:
                    estoque_atual = doc.to_dict().get('estoque_atual', 0)
                    nova_qtd = estoque_atual + sobra
                else:
                    nova_qtd = sobra
                
                ref.set({
                    "nome": item['nome'],
                    "marca": nome_marca,
                    "mercado": item.get('mercado', ''),
                    "estoque_atual": nova_qtd,
                    "unidade": item['unidade'],
                    "preco_pago": item['preco_compra'],
                    "tam_orig": item['tam_pacote']
                })

def pegar_receitas():
    docs = db.collection("recipes").stream()
    return [doc.to_dict() for doc in docs]

# --- 4. APP ---

# Login Simples
with st.sidebar:
    st.title("🔐 Acesso")
    senha = st.text_input("Senha", type="password")
    if senha != st.secrets.get("senha_app", "admin"):
        st.warning("Bloqueado")
        st.stop()
    st.success("Logado")

st.title("🍳 Gestor de Receitas & Sobras")

# Estado temporário
if 'ingredientes_temp' not in st.session_state:
    st.session_state.ingredientes_temp = []

# ABAS - Mantendo a estrutura visual que você gostou
aba_criar, aba_estoque, aba_projeto, aba_ver = st.tabs([
    "📝 Criar Receita", 
    "📦 Ver Sobras/Estoque", 
    "🔮 Projetar Produção",
    "📊 Editar/Apagar"
])

# ==========================================
# ABA 1: CRIAR (A CARA ANTIGA + MARCAS)
# ==========================================
with aba_criar:
    st.caption("Crie sua receita. O sistema calcula o custo e guarda o que sobrar no pacote automaticamente.")
    
    with st.container(border=True):
        st.subheader("Adicionar Ingrediente")
        
        # Linha 1: O que é?
        c1, c2, c3 = st.columns([2, 1, 1])
        nome = c1.text_input("Nome do Ingrediente", placeholder="Ex: Creme de Leite")
        marca = c2.text_input("Marca (Opcional)", placeholder="Ex: Nestlé")
        mercado = c3.text_input("Mercado (Opcional)", placeholder="Ex: Atacadão")
        
        # Linha 2: Valores
        c4, c5, c6, c7 = st.columns(4)
        preco = c4.number_input("Preço Pago (R$)", min_value=0.0, format="%.2f")
        pacote = c5.number_input("Tamanho do Pacote", min_value=0.0)
        unidade = c6.selectbox("Unidade", ["g", "ml", "unid", "kg", "L"])
        usado = c7.number_input("Qtd. Usada na Receita", min_value=0.0)
        
        # Botão
        if st.button("⬇️ Adicionar", type="primary"):
            if nome and pacote > 0 and usado > 0:
                custo_u = preco / pacote
                st.session_state.ingredientes_temp.append({
                    "nome": nome,
                    "marca": marca if marca else "Genérico",
                    "mercado": mercado,
                    "preco_compra": preco,
                    "tam_pacote": pacote,
                    "unidade": unidade,
                    "qtd_usada": usado,
                    "custo_unitario": custo_u,
                    "custo_final": custo_u * usado
                })
                st.rerun()
            else:
                st.error("Preencha nome, tamanho do pacote e quantidade usada.")

    # Lista Atual
    if st.session_state.ingredientes_temp:
        st.divider()
        st.subheader("Rascunho da Receita")
        df = pd.DataFrame(st.session_state.ingredientes_temp)
        st.dataframe(
            df[["nome", "marca", "qtd_usada", "unidade", "custo_final"]].style.format({"custo_final": "R$ {:.2f}"}),
            use_container_width=True
        )
        
        # Salvar
        with st.form("salvar_form"):
            col_n, col_a = st.columns(2)
            rec_nome = col_n.text_input("Nome da Receita")
            rec_autor = col_a.text_input("Autor")
            
            st.write("---")
            # Checkbox Importante
            guardar_sobras = st.checkbox("Salvar as sobras no estoque?", value=True, help="Se marcado, o que não foi usado do pacote vai para a aba 'Ver Sobras'.")
            
            if st.form_submit_button("💾 Salvar Receita"):
                if rec_nome:
                    salvar_receita_e_atualizar_sobras(rec_nome, rec_autor, st.session_state.ingredientes_temp, guardar_sobras)
                    st.success(f"Receita '{rec_nome}' salva!")
                    if guardar_sobras:
                        st.info("📦 Sobras adicionadas ao estoque com sucesso.")
                    st.session_state.ingredientes_temp = []
                    st.rerun()
        
        if st.button("Limpar Rascunho"):
            st.session_state.ingredientes_temp = []
            st.rerun()

# ==========================================
# ABA 2: ESTOQUE (AS SOBRAS)
# ==========================================
with aba_estoque:
    st.header("Armazém de Sobras")
    st.caption("Aqui fica tudo que sobrou das compras das receitas anteriores.")
    
    estoque = pegar_estoque()
    
    if estoque:
        # Filtra para mostrar só o que tem saldo positivo
        estoque_ativo = [e for e in estoque if e['estoque_atual'] > 0]
        
        if estoque_ativo:
            df_est = pd.DataFrame(estoque_ativo)
            st.dataframe(
                df_est[["nome", "marca", "estoque_atual", "unidade", "mercado"]].style.format({"estoque_atual": "{:.1f}"}),
                use_container_width=True
            )
        else:
            st.info("Nenhuma sobra registrada no momento.")
    else:
        st.info("O armazém está vazio. Crie receitas marcando 'Salvar Sobras' para preencher aqui.")

# ==========================================
# ABA 3: PROJETAR PRODUÇÃO (REUTILIZAÇÃO)
# ==========================================
with aba_projeto:
    st.header("Planejador de Produção")
    st.caption("Se eu quiser fazer 5 bolos, minhas sobras são suficientes?")
    
    receitas = pegar_receitas()
    estoque_atual = pegar_estoque()
    
    if receitas and estoque_atual:
        # 1. Seleciona Receita
        rec_sel = st.selectbox("Escolha a Receita", [r['name'] for r in receitas])
        dados_rec = next(r for r in receitas if r['name'] == rec_sel)
        
        # 2. Quantidade
        qtd_fazer = st.number_input("Quantidade a produzir", min_value=1, value=1)
        
        st.divider()
        st.subheader("Análise de Estoque")
        
        relatorio = []
        pode_fazer = True
        
        for item in dados_rec['ingredients']:
            necessario = item['qtd_usada'] * qtd_fazer
            
            # Soma todas as marcas disponíveis desse ingrediente
            disponivel = sum(e['estoque_atual'] for e in estoque_atual if e['nome'] == item['nome'])
            
            saldo = disponivel - necessario
            status = "✅ OK" if saldo >= 0 else "❌ COMPRAR"
            
            relatorio.append({
                "Ingrediente": item['nome'],
                "Necessário": necessario,
                "Em Estoque": disponivel,
                "Falta/Sobra": saldo,
                "Status": status
            })
        
        st.dataframe(pd.DataFrame(relatorio), use_container_width=True)
        
        # Botão de Baixa Real
        if st.button("Confirmar Produção e Deduzir do Estoque"):
            # Lógica simplificada de baixa
            falta_algo = any(r['Falta/Sobra'] < 0 for r in relatorio)
            
            if falta_algo:
                st.error("Você não tem estoque suficiente para isso. Compre os itens que faltam.")
            else:
                # Processo de baixa
                for item in dados_rec['ingredients']:
                    a_abater = item['qtd_usada'] * qtd_fazer
                    
                    # Busca lotes disponíveis
                    lotes = [e for e in pegar_estoque() if e['nome'] == item['nome'] and e['estoque_atual'] > 0]
                    
                    for lote in lotes:
                        if a_abater <= 0: break
                        
                        id_lote = f"{lote['nome']}_{lote['marca']}".replace(" ", "_").lower()
                        
                        if lote['estoque_atual'] >= a_abater:
                            db.collection("inventory").document(id_lote).update({"estoque_atual": lote['estoque_atual'] - a_abater})
                            a_abater = 0
                        else:
                            a_abater -= lote['estoque_atual']
                            db.collection("inventory").document(id_lote).update({"estoque_atual": 0})
                
                st.success("Estoque atualizado! Itens removidos do armazém.")
                st.rerun()

# ==========================================
# ABA 4: VER/EDITAR (NORMAL)
# ==========================================
with aba_ver:
    st.header("Biblioteca")
    if receitas:
        r_sel = st.selectbox("Ver Receita", [r['name'] for r in receitas], key="v_sel")
        d_rec = next(r for r in receitas if r['name'] == r_sel)
        
        st.dataframe(pd.DataFrame(d_rec['ingredients'])[["nome", "marca", "qtd_usada", "custo_final"]], use_container_width=True)
        
        custo = d_rec['total_cost']
        c1, c2 = st.columns(2)
        c1.metric("Custo Receita", f"R$ {custo:.2f}")
        
        pv = c2.number_input("Preço Venda", value=custo*3)
        if pv:
            lucro = pv - custo
            margem = (lucro/pv)*100
            st.write(f"Margem: **{margem:.1f}%** (Lucro R$ {lucro:.2f})")
        
        if st.button("🗑️ Apagar Receita"):
            doc_del = f"{d_rec['name']}_{d_rec['author']}".replace(" ", "_").lower()
            db.collection("recipes").document(doc_del).delete()
            st.rerun()
