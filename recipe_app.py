import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json

# --- 1. CONFIGURAÇÃO VISUAL ---
st.set_page_config(
    page_title="Panela de Controle - Precificação", 
    layout="wide", 
    page_icon="🥘",
    initial_sidebar_state="collapsed"
)

# CSS Customizado
st.markdown("""
    <style>
    .stButton>button { border-radius: 20px; font-weight: bold; width: 100%; }
    .stDataFrame { border-radius: 10px; }
    h1 { color: #ff4b4b; }
    div[data-testid="stNumberInput"] input { font-weight: bold; color: #333; }
    </style>
""", unsafe_allow_html=True)

# --- 2. CONEXÃO SEGURA ---
@st.cache_resource
def conectar():
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
                st.error("🔌 Erro de conexão com o banco.")
                st.stop()
    return firestore.client()

db = conectar()

# --- 3. LÓGICA DO SISTEMA ---
def pegar_receitas():
    docs = db.collection("recipes").stream()
    lista = []
    for doc in docs:
        d = doc.to_dict()
        d['id'] = doc.id
        lista.append(d)
    return lista

def salvar_receita(nome, autor, ingredientes):
    doc_id = f"{nome}_{autor}".replace(" ", "_").lower()
    custo = sum(i['custo_final'] for i in ingredientes)
    
    db.collection("recipes").document(doc_id).set({
        "name": nome,
        "author": autor,
        "ingredients": ingredientes,
        "total_cost": custo,
        "updated_at": firestore.SERVER_TIMESTAMP
    }, merge=True)

def apagar_receita(doc_id):
    db.collection("recipes").document(doc_id).delete()

# --- 4. FUNÇÃO VISUAL (CARTÕES COLORIDOS) ---
def cartao_financeiro(titulo, valor, cor_fundo, cor_texto, icone):
    st.markdown(f"""
    <div style="background-color: {cor_fundo}; padding: 15px; border-radius: 15px; border-left: 5px solid {cor_texto}; margin-bottom: 10px;">
        <p style="color: {cor_texto}; font-size: 14px; margin: 0; font-weight: bold;">{icone} {titulo}</p>
        <p style="color: #333; font-size: 24px; margin: 0; font-weight: bold;">R$ {valor:,.2f}</p>
    </div>
    """, unsafe_allow_html=True)

# --- 5. INTERFACE ---
c_head1, c_head2 = st.columns([1, 8])
c_head1.markdown("# 🥘")
c_head2.title("Panela de Controle | Ficha Técnica")

with st.sidebar:
    st.caption("Admin")
    if st.text_input("Senha", type="password") != st.secrets.get("senha_app", "admin"):
        st.warning("🔒 Digite a senha para acessar."); st.stop()

# ESTADO
if 'carrinho' not in st.session_state: st.session_state.carrinho = []

# ABAS PRINCIPAIS
aba_criar, aba_listar, aba_calculadora = st.tabs([
    "📝 Nova Receita", 
    "📚 Minhas Receitas", 
    "⚖️ Calculadora (X Unidades)"
])

# ==================================================
# ABA 1: CRIAR RECEITA (Foco em Custo Base)
# ==================================================
with aba_criar:
    st.caption("Crie a ficha técnica de 1 unidade/lote base da sua receita.")
    
    col_input, col_preview = st.columns([1, 1.2])
    
    with col_input:
        with st.container(border=True):
            st.subheader("Adicionar Ingrediente")
            nome_ing = st.text_input("Nome do Ingrediente", placeholder="ex: Farinha de Trigo")
            
            c1, c2 = st.columns(2)
            p_compra = c1.number_input("Preço do Pacote Fechado (R$)", 0.0, format="%.2f")
            t_pacote = c2.number_input("Tamanho do Pacote", 0.0, help="ex: 1000 se for 1kg e você for usar em gramas.")
            
            c3, c4 = st.columns(2)
            unid = c3.selectbox("Medida", ["g", "ml", "unid"])
            uso = c4.number_input("Quanto vai na receita?", 0.0)
            
            if t_pacote > 0 and uso > 0:
                custo_previsto = (p_compra / t_pacote) * uso
                st.info(f"💰 Custo Proporcional: **R$ {custo_previsto:.2f}**")
            
            if st.button("⬇️ Adicionar Item"):
                if t_pacote > 0 and uso > 0 and nome_ing:
                    custo = (p_compra / t_pacote) * uso
                    st.session_state.carrinho.append({
                        "nome": nome_ing, "preco_compra": p_compra, "tam_pacote": t_pacote,
                        "unidade": unid, "qtd_usada": uso, "custo_final": custo
                    })
                    st.rerun()
                else:
                    st.error("Preencha todos os campos e certifique-se que o tamanho do pacote não é zero.")

    with col_preview:
        st.subheader("Ficha Técnica Atual")
        if st.session_state.carrinho:
            df = pd.DataFrame(st.session_state.carrinho)
            st.dataframe(df[["nome", "qtd_usada", "unidade", "custo_final"]], use_container_width=True, hide_index=True)
            
            custo_total = df['custo_final'].sum()
            cartao_financeiro("Custo Total da Receita", custo_total, "#FFF3E0", "#FF9800", "🏷️")
            
            with st.form("save_recipe"):
                n_rec = st.text_input("Nome da Receita (ex: Bolo de Cenoura Inteiro)")
                n_aut = st.text_input("Criador/Chef")
                if st.form_submit_button("💾 Salvar Receita no Banco"):
                    if n_rec:
                        salvar_receita(n_rec, n_aut, st.session_state.carrinho)
                        st.balloons()
                        st.session_state.carrinho = []
                        st.rerun()
                    else:
                        st.error("Dê um nome para a receita antes de salvar.")
            
            if st.button("🗑️ Limpar Rascunho"):
                st.session_state.carrinho = []; st.rerun()
        else:
            st.info("A ficha técnica está vazia. Adicione ingredientes ao lado.")

# ==================================================
# ABA 2: MINHAS RECEITAS (Banco de Dados)
# ==================================================
with aba_listar:
    st.subheader("📚 Banco de Receitas")
    receitas_salvas = pegar_receitas()
    
    if receitas_salvas:
        for rec in receitas_salvas:
            with st.expander(f"🍽️ {rec['name']} - Custo Base: R$ {rec['total_cost']:.2f}"):
                st.caption(f"Autor: {rec.get('author', 'Desconhecido')}")
                df_ing = pd.DataFrame(rec['ingredients'])
                st.dataframe(df_ing[["nome", "qtd_usada", "unidade", "custo_final"]], use_container_width=True, hide_index=True)
                
                if st.button("🗑️ Apagar esta receita", key=f"del_{rec['id']}"):
                    apagar_receita(rec['id'])
                    st.rerun()
    else:
        st.info("Nenhuma receita salva ainda.")

# ==================================================
# ABA 3: CALCULADORA (Custo para X unidades)
# ==================================================
with aba_calculadora:
    st.subheader("⚖️ Planejamento de Produção")
    st.caption("Descubra quanto vai custar e o que precisa comprar para fazer X quantidades de uma receita.")
    
    receitas_calc = pegar_receitas()
    
    if receitas_calc:
        c_sel, c_qtd = st.columns([2, 1])
        r_escolhida = c_sel.selectbox("Selecione a Receita", [r['name'] for r in receitas_calc])
        dados_rec = next(r for r in receitas_calc if r['name'] == r_escolhida)
        
        multiplicador = c_qtd.number_input("Quantas receitas vai fazer?", min_value=1.0, value=1.0, step=1.0)
        
        st.divider()
        
        custo_multiplicado = dados_rec['total_cost'] * multiplicador
        
        col_res1, col_res2 = st.columns(2)
        with col_res1:
            cartao_financeiro("Custo para Produção", custo_multiplicado, "#FFEBEE", "#D32F2F", "🔴")
        with col_res2:
            sugestao_venda = custo_multiplicado * 3 # Exemplo de markup (x3)
            cartao_financeiro("Sugestão de Venda (Markup 3x)", sugestao_venda, "#E8F5E9", "#388E3C", "🤑")
        
        st.markdown("### 🛒 Lista de Compras Exata")
        lista_compras = []
        for ing in dados_rec['ingredients']:
            qtd_total_necessaria = ing['qtd_usada'] * multiplicador
            custo_ing_total = ing['custo_final'] * multiplicador
            lista_compras.append({
                "Ingrediente": ing['nome'],
                "Quantidade Necessária": f"{qtd_total_necessaria:.2f} {ing['unidade']}",
                "Custo Proporcional": f"R$ {custo_ing_total:.2f}"
            })
            
        st.dataframe(pd.DataFrame(lista_compras), use_container_width=True, hide_index=True)
        
    else:
        st.warning("Crie e salve uma receita na primeira aba para usar a calculadora.")
