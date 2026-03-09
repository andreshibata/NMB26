import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json
import math

# --- 1. CONFIGURAÇÃO VISUAL ---
st.set_page_config(
    page_title="Panela de Controle - Precificação", 
    layout="wide", 
    page_icon="🥘",
    initial_sidebar_state="collapsed"
)

# CSS Customizado - Atualizado para suportar Dark Mode nativamente
st.markdown("""
    <style>
    .stButton>button { border-radius: 10px; font-weight: bold; width: 100%; }
    .stDataFrame { border-radius: 10px; }
    h1 { color: #ff4b4b; }
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

# --- 4. FUNÇÃO VISUAL (CARTÕES ADAPTATIVOS AO DARK MODE) ---
def cartao_financeiro(titulo, valor, cor_borda, icone, subtitulo=""):
    # Usando CSS variables nativas do Streamlit para texto e fundo
    st.markdown(f"""
    <div style="background-color: var(--secondary-background-color); padding: 15px; border-radius: 10px; border-left: 5px solid {cor_borda}; margin-bottom: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        <p style="color: var(--text-color); font-size: 14px; margin: 0; font-weight: bold; opacity: 0.8;">{icone} {titulo}</p>
        <p style="color: var(--text-color); font-size: 24px; margin: 5px 0 0 0; font-weight: bold;">R$ {valor:,.2f}</p>
        <p style="color: var(--text-color); font-size: 12px; margin: 0; opacity: 0.6;">{subtitulo}</p>
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

# ABAS PRINCIPAIS
aba_criar, aba_listar, aba_calculadora = st.tabs([
    "📝 Nova Receita", 
    "📚 Minhas Receitas", 
    "⚖️ Calculadora de Produção"
])

# ==================================================
# ABA 1: CRIAR RECEITA (TABELA DINÂMICA)
# ==================================================
with aba_criar:
    st.caption("Monte sua receita. Adicione linhas à tabela abaixo para incluir novos ingredientes.")
    
    col_info, col_vazia = st.columns([2, 1])
    with col_info:
        nome_receita = st.text_input("Nome da Receita (ex: Bolo de Cenoura)")
        autor_receita = st.text_input("Criador/Chef", value="Chef")

    st.markdown("### 🛒 Ingredientes da Receita")
    
    # Criando o DataFrame vazio base para o Editor
    if 'df_ingredientes' not in st.session_state:
        st.session_state.df_ingredientes = pd.DataFrame(
            columns=["Ingrediente", "Preco_Pacote", "Tam_Pacote", "Medida", "Qtd_Usada"]
        )

    # Editor de dados do Streamlit (Permite adicionar/remover linhas livremente)
    edited_df = st.data_editor(
        st.session_state.df_ingredientes,
        num_rows="dynamic", # Essa configuração é a mágica que permite adicionar linhas
        column_config={
            "Ingrediente": st.column_config.TextColumn("Nome do Ingrediente", required=True),
            "Preco_Pacote": st.column_config.NumberColumn("Preço do Pacote (R$)", min_value=0.01, format="%.2f"),
            "Tam_Pacote": st.column_config.NumberColumn("Tamanho Pacote", min_value=0.01),
            "Medida": st.column_config.SelectboxColumn("Medida", options=["g", "ml", "unid", "kg", "L"]),
            "Qtd_Usada": st.column_config.NumberColumn("Qtd Usada na Receita", min_value=0.01)
        },
        use_container_width=True,
        hide_index=True
    )

    # Cálculo dinâmico do custo enquanto preenche a tabela
    custo_total_estimado = 0
    ingredientes_processados = []
    
    # Filtrar apenas as linhas onde todos os dados foram preenchidos
    linhas_validas = edited_df.dropna(how='any')
    
    for _, row in linhas_validas.iterrows():
        if row['Tam_Pacote'] > 0:
            custo_linha = (row['Preco_Pacote'] / row['Tam_Pacote']) * row['Qtd_Usada']
            custo_total_estimado += custo_linha
            
            # Prepara o formato para salvar no banco depois
            ingredientes_processados.append({
                "nome": row['Ingrediente'],
                "preco_compra": row['Preco_Pacote'],
                "tam_pacote": row['Tam_Pacote'],
                "unidade": row['Medida'],
                "qtd_usada": row['Qtd_Usada'],
                "custo_final": custo_linha
            })

    # Mostrar o custo atualizado em tempo real
    if custo_total_estimado > 0:
        st.info(f"💰 Custo Base Atual da Receita: **R$ {custo_total_estimado:.2f}**")

    # Botão de salvar
    if st.button("💾 Salvar Receita no Banco", type="primary"):
        if not nome_receita:
            st.error("⚠️ Dê um nome para a receita antes de salvar.")
        elif not ingredientes_processados:
            st.error("⚠️ Preencha os ingredientes corretamente antes de salvar.")
        else:
            salvar_receita(nome_receita, autor_receita, ingredientes_processados)
            st.balloons()
            st.success(f"Receita '{nome_receita}' salva com sucesso!")
            # Reseta a tabela
            st.session_state.df_ingredientes = pd.DataFrame(columns=["Ingrediente", "Preco_Pacote", "Tam_Pacote", "Medida", "Qtd_Usada"])
            st.rerun()

# ==================================================
# ABA 2: MINHAS RECEITAS
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
# ABA 3: CALCULADORA (X Unidades & Pacotes Inteiros)
# ==================================================
with aba_calculadora:
    st.subheader("⚖️ Planejamento de Produção & Compras")
    st.caption("Descubra o custo de fabricação e quanto dinheiro precisa para comprar as embalagens fechadas no mercado.")
    
    receitas_calc = pegar_receitas()
    
    if receitas_calc:
        c_sel, c_qtd = st.columns([2, 1])
        r_escolhida = c_sel.selectbox("Selecione a Receita", [r['name'] for r in receitas_calc])
        dados_rec = next(r for r in receitas_calc if r['name'] == r_escolhida)
        
        multiplicador = c_qtd.number_input("Quantas receitas vai fazer?", min_value=1.0, value=1.0, step=1.0)
        
        st.divider()
        
        custo_proporcional_total = 0 
        desembolso_mercado_total = 0 
        lista_compras = []
        
        for ing in dados_rec['ingredients']:
            # 1. Necessidade exata
            qtd_total_necessaria = ing['qtd_usada'] * multiplicador
            custo_prop_ing = ing['custo_final'] * multiplicador
            custo_proporcional_total += custo_prop_ing
            
            # 2. Lógica de Mercado
            tam_pacote = ing['tam_pacote']
            preco_pacote = ing['preco_compra']
            
            pacotes_necessarios = math.ceil(qtd_total_necessaria / tam_pacote)
            custo_mercado_ing = pacotes_necessarios * preco_pacote
            desembolso_mercado_total += custo_mercado_ing
            
            lista_compras.append({
                "Ingrediente": ing['nome'],
                "Uso Exato": f"{qtd_total_necessaria:.1f} {ing['unidade']}",
                "Comprar (Pacotes)": f"{pacotes_necessarios}x ({tam_pacote}{ing['unidade']})",
                "Custo Proporcional": f"R$ {custo_prop_ing:.2f}",
                "Desembolso Caixa": f"R$ {custo_mercado_ing:.2f}"
            })

        # Exibindo os Cards Financeiros (Agora adaptados para Dark Mode)
        col_res1, col_res2, col_res3 = st.columns(3)
        with col_res1:
            cartao_financeiro("Custo Proporcional", custo_proporcional_total, "#FF9800", "⚖️", "Custo real das gramas usadas.")
        with col_res2:
            cartao_financeiro("Desembolso no Mercado", desembolso_mercado_total, "#F44336", "🛒", "Valor em embalagens fechadas.")
        with col_res3:
            sugestao_venda = custo_proporcional_total * 3
            cartao_financeiro("Sugestão de Venda", sugestao_venda, "#4CAF50", "🤑", "Markup 3x sobre o Proporcional.")
        
        st.markdown("### 📝 Lista de Compras Exata")
        st.dataframe(pd.DataFrame(lista_compras), use_container_width=True, hide_index=True)
        
    else:
        st.warning("Crie e salve uma receita na primeira aba para usar a calculadora.")

