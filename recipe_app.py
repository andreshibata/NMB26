import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Calculadora de Receitas", layout="wide", page_icon="🍳")

# --- 2. CONEXÃO SEGURA (BANCO DE DADOS) ---
@st.cache_resource
def conectar_banco():
    if not firebase_admin._apps:
        try:
            # Tenta conectar com arquivo local (no seu computador)
            cred = credentials.Certificate("firebase_key.json") 
            firebase_admin.initialize_app(cred)
        except:
            # Tenta conectar com segredos da nuvem (na internet)
            if "textkey" in st.secrets:
                key_dict = json.loads(st.secrets["textkey"])
                cred = credentials.Certificate(key_dict)
                firebase_admin.initialize_app(cred)
            else:
                st.error("❌ Erro: Chave do banco de dados não encontrada.")
                st.stop()
    return firestore.client()

db = conectar_banco()

# --- 3. FUNÇÕES (O CÉREBRO) ---

def pegar_despensa_dict():
    """Baixa os ingredientes para preencher o formulário automaticamente"""
    docs = db.collection("ingredients").stream()
    # Cria um dicionário: {'Farinha': {'preco': 5.0...}, ...}
    return {doc.to_dict()['name']: doc.to_dict() for doc in docs}

def salvar_receita(nome, autor, ingredientes):
    # 1. Salva a Receita
    doc_id = f"{nome.replace(' ', '_').lower()}_{autor.replace(' ', '_').lower()}"
    custo_total = sum(i['custo_final'] for i in ingredientes)
    
    db.collection("recipes").document(doc_id).set({
        "name": nome,
        "author": autor,
        "ingredients": ingredientes,
        "total_cost": custo_total,
        "created_at": firestore.SERVER_TIMESTAMP
    })
    
    # 2. Atualiza a Despensa Global (Salva os preços novos automaticamente)
    for item in ingredientes:
        safe_id = item['nome'].replace(" ", "_").lower()
        db.collection("ingredients").document(safe_id).set({
            "name": item['nome'],
            "price": item['preco_compra'],
            "pkg_amount": item['tam_pacote'],
            "unit": item['unidade'],
            "price_per_unit": item['custo_unitario']
        })

def pegar_todas_receitas():
    docs = db.collection("recipes").stream()
    return [doc.to_dict() for doc in docs]

# --- 4. ESTADO DA SESSÃO (MEMÓRIA TEMPORÁRIA) ---
if 'ingredientes_temp' not in st.session_state:
    st.session_state.ingredientes_temp = []

# --- 5. APLICATIVO ---

# --- BARRA LATERAL (LOGIN) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3565/3565418.png", width=100)
    st.title("Acesso Restrito 🔒")
    
    # Verifica a senha definida nos "Secrets"
    senha_digitada = st.text_input("Digite a Senha do Grupo", type="password")
    
    # Se não houver senha configurada, usa "admin" como padrão
    senha_correta = st.secrets.get("senha_app", "admin")
    
    if senha_digitada == senha_correta:
        st.success("Acesso Liberado! ✅")
        acesso_permitido = True
    else:
        st.warning("Digite a senha para usar.")
        acesso_permitido = False

# Se a senha estiver errada, o app para de carregar aqui
if not acesso_permitido:
    st.stop()

# --- TELA PRINCIPAL ---
st.title("🍳 Calculadora de Custos & Precificação")

# Busca ingredientes já conhecidos para facilitar
despensa_conhecida = pegar_despensa_dict()
nomes_conhecidos = sorted(list(despensa_conhecida.keys()))

aba_criar, aba_ver = st.tabs(["📝 Criar Receita", "📊 Analisar Lucro"])

# =========================================
# ABA 1: CRIADOR DE RECEITAS
# =========================================
with aba_criar:
    st.caption("Adicione os ingredientes. O sistema lembra os preços automaticamente para a próxima vez.")
    
    with st.container(border=True):
        st.subheader("1. Adicionar Ingrediente")
        
        c1, c2 = st.columns([1, 1])
        
        # Escolha: Usar algo que já existe ou Criar Novo
        tipo_entrada = c1.radio("Tipo de Entrada:", ["Escolher Existente", "Criar Novo"], horizontal=True, label_visibility="collapsed")
        
        # Lógica para preencher os campos automaticamente
        if tipo_entrada == "Escolher Existente" and nomes_conhecidos:
            nome_selecionado = c1.selectbox("Selecione o Ingrediente", nomes_conhecidos)
            dados = despensa_conhecida[nome_selecionado]
            
            # Preenche as variáveis com o que veio do banco
            val_preco = float(dados['price'])
            val_tam = float(dados['pkg_amount'])
            val_unid = dados['unit']
            nome_final = nome_selecionado
        else:
            nome_final = c1.text_input("Nome do Ingrediente", placeholder="Ex: Leite Condensado")
            val_preco, val_tam, val_unid = 0.0, 0.0, "g"

        # Os 4 Campos Numéricos
        col_p, col_t, col_u, col_use = st.columns(4)
        
        preco_compra = col_p.number_input("Preço Pago (R$)", value=val_preco, min_value=0.0, step=0.50, format="%.2f")
        tam_pacote = col_t.number_input("Tamanho do Pacote", value=val_tam, min_value=0.0)
        unidade = col_u.selectbox("Unidade", ["g", "ml", "unid", "kg", "L"], index=["g", "ml", "unid", "kg", "L"].index(val_unid) if val_unid in ["g", "ml", "unid", "kg", "L"] else 0)
        qtd_usada = col_use.number_input("Qtd. Usada na Receita", min_value=0.0)

        # Botão Adicionar
        if st.button("⬇️ Adicionar à Lista", type="primary"):
            if nome_final and tam_pacote > 0 and qtd_usada > 0:
                # Matemática
                custo_unitario = preco_compra / tam_pacote
                custo_final = custo_unitario * qtd_usada
                
                st.session_state.ingredientes_temp.append({
                    "nome": nome_final,
                    "preco_compra": preco_compra,
                    "tam_pacote": tam_pacote,
                    "unidade": unidade,
                    "qtd_usada": qtd_usada,
                    "custo_unitario": custo_unitario,
                    "custo_final": custo_final
                })
                st.rerun()
            else:
                st.error("Preencha o Tamanho do Pacote e a Quantidade Usada.")

    # --- LISTA ATUAL ---
    if st.session_state.ingredientes_temp:
        st.divider()
        st.subheader("Ingredientes da Receita Atual")
        
        df = pd.DataFrame(st.session_state.ingredientes_temp)
        
        # Mostra a tabela bonita
        st.dataframe(
            df[["nome", "qtd_usada", "unidade", "custo_final"]].style.format({"custo_final": "R$ {:.2f}", "qtd_usada": "{:.1f}"}),
            use_container_width=True
        )
        
        total_atual = df['custo_final'].sum()
        st.write(f"### Custo Total: R$ {total_atual:,.2f}")
        
        # --- FORMULÁRIO DE SALVAR ---
        with st.form("form_salvar"):
            st.write("---")
            st.subheader("2. Finalizar")
            c_nome, c_autor = st.columns(2)
            input_receita = c_nome.text_input("Nome da Receita", placeholder="Ex: Bolo de Cenoura")
            input_autor = c_autor.text_input("Seu Nome", placeholder="Ex: João")
            
            if st.form_submit_button("💾 Salvar Receita no Banco de Dados"):
                if input_receita and input_autor:
                    salvar_receita(input_receita, input_autor, st.session_state.ingredientes_temp)
                    st.success(f"Sucesso! Receita '{input_receita}' salva e preços atualizados!")
                    st.session_state.ingredientes_temp = [] # Limpa a lista
                    st.rerun()
                else:
                    st.warning("Preencha o Nome da Receita e Seu Nome.")
        
        if st.button("🗑️ Limpar Tudo"):
            st.session_state.ingredientes_temp = []
            st.rerun()

# =========================================
# ABA 2: VISUALIZAR E CALCULAR LUCRO
# =========================================
with aba_ver:
    st.header("Biblioteca de Receitas")
    
    todas_receitas = pegar_todas_receitas()
    
    if todas_receitas:
        opcoes = [f"{r['name']} (por {r['author']})" for r in todas_receitas]
        escolha = st.selectbox("Escolha uma Receita", opcoes)
        
        dados_rec = next(r for r in todas_receitas if f"{r['name']} (por {r['author']})" == escolha)
        
        # Tabela Detalhada
        df_ver = pd.DataFrame(dados_rec['ingredients'])
        st.dataframe(
            df_ver[["nome", "preco_compra", "tam_pacote", "qtd_usada", "custo_final"]].style.format({
                "preco_compra": "R$ {:.2f}",
                "custo_final": "R$ {:.2f}",
                "tam_pacote": "{:.0f}",
                "qtd_usada": "{:.0f}"
            }),
            use_container_width=True
        )
        
        st.divider()
        
        # Calculadora de Margem
        custo = dados_rec['total_cost']
        
        c_math1, c_math2, c_math3 = st.columns(3)
        c_math1.metric("Custo de Produção", f"R$ {custo:.2f}")
        
        preco_venda = c_math2.number_input("Preço de Venda Sugerido (R$)", value=custo * 3.0, step=1.0)
        
        if preco_venda > 0:
            lucro = preco_venda - custo
            margem = (lucro / preco_venda) * 100
            
            c_math3.metric("Margem de Lucro", f"{margem:.1f}%", delta=f"R$ {lucro:.2f}")
            
            if margem < 30:
                st.warning("⚠️ Margem Baixa (Menor que 30%)")
            elif margem > 50:
                st.success("🚀 Margem Excelente (Maior que 50%)")
            else:
                st.info("✅ Margem Saudável")
    else:
        st.info("Nenhuma receita salva ainda.")