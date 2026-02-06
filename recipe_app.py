import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json
from datetime import datetime

# --- 1. CONFIGURAÇÃO VISUAL ---
st.set_page_config(
    page_title="Planejador de Produção", 
    layout="wide", 
    page_icon="🏭",
    initial_sidebar_state="collapsed"
)

# Estilo Limpo
st.markdown("""
    <style>
    .stMetric { background-color: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 5px solid #ff4b4b; }
    .big-font { font-size: 18px !important; font-weight: bold; }
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
                st.error("Erro de conexão 🔌")
                st.stop()
    return firestore.client()

db = conectar()

# --- 3. LÓGICA DE PRODUÇÃO ---

def pegar_receitas():
    return [doc.to_dict() for doc in db.collection("recipes").stream()]

def pegar_estoque():
    return [doc.to_dict() for doc in db.collection("inventory").stream()]

def salvar_receita(nome, autor, ingredientes):
    doc_id = f"{nome}_{autor}".replace(" ", "_").lower()
    custo = sum(i['custo_final'] for i in ingredientes)
    
    db.collection("recipes").document(doc_id).set({
        "name": nome,
        "author": autor,
        "ingredients": ingredientes,
        "total_cost": custo,
        "created_at": firestore.SERVER_TIMESTAMP
    })
    
    # Atualiza preços de referência na despensa (para facilitar compras futuras)
    for item in ingredientes:
        safe_id = f"{item['nome']}_generico".replace(" ", "_").lower()
        db.collection("inventory").document(safe_id).set({
            "nome": item['nome'],
            "marca": item.get('marca', 'Genérica'),
            "preco_ref": item['preco_compra'],
            "tam_ref": item['tam_pacote'],
            "unidade": item['unidade'],
            "ultimo_uso": firestore.SERVER_TIMESTAMP
        }, merge=True)

def confirmar_producao(fila_producao):
    """Baixa os ingredientes do estoque e registra a produção"""
    estoque = pegar_estoque()
    
    for item_plan in fila_producao:
        receita = item_plan['dados_receita']
        qtd_fazer = item_plan['qtd']
        
        for ing in receita['ingredients']:
            necessario = ing['qtd_usada'] * qtd_fazer
            nome = ing['nome']
            
            # Busca o item no estoque para abater
            item_est = next((e for e in estoque if e['nome'] == nome), None)
            
            if item_est:
                safe_id = f"{item_est['nome']}_generico".replace(" ", "_").lower()
                atual = item_est.get('estoque_atual', 0)
                # Abate do estoque (não deixa ficar negativo, zera se acabar)
                novo_saldo = max(0, atual - necessario)
                
                db.collection("inventory").document(safe_id).update({"estoque_atual": novo_saldo})
                # Atualiza lista local
                item_est['estoque_atual'] = novo_saldo 
                
    # Registra no Histórico
    db.collection("history").add({
        "tipo": "Produção Realizada",
        "resumo": [f"{f['qtd']}x {f['nome']}" for f in fila_producao],
        "data": firestore.SERVER_TIMESTAMP,
        "custo_total": sum(f['total_custo'] for f in fila_producao)
    })
    return True

# --- 4. INTERFACE ---

c1, c2 = st.columns([1, 10])
c1.title("👩‍🍳")
c2.title("Planejador de Produção")

with st.sidebar:
    st.caption("Acesso Restrito")
    if st.text_input("Senha", type="password") != st.secrets.get("senha_app", "admin"):
        st.warning("🔒"); st.stop()

# Armazena a fila de produção na memória
if 'fila_producao' not in st.session_state: st.session_state.fila_producao = []

# ABAS
aba_plan, aba_rec, aba_est, aba_hist = st.tabs([
    "🚀 Planejar Produção", 
    "📖 Receitas", 
    "📦 Despensa", 
    "📜 Histórico"
])

# ==================================================
# ABA 1: O PLANEJADOR (FOCO NO QUE PRECISA)
# ==================================================
with aba_plan:
    st.caption("Adicione o que você quer cozinhar. O sistema gera a lista de compras/separação.")
    
    col_input, col_resumo = st.columns([1, 1.5])
    
    # --- 1. O QUE VAMOS FAZER? ---
    with col_input:
        with st.container(border=True):
            st.subheader("1. Adicionar à Fila")
            receitas = pegar_receitas()
            
            if receitas:
                # Seleção
                rec_sel = st.selectbox("Escolha a Receita", [r['name'] for r in receitas])
                dados_rec = next(r for r in receitas if r['name'] == rec_sel)
                
                # Quantidade
                qtd = st.number_input("Quantidade a produzir", min_value=1, value=1)
                
                # Botão Add
                if st.button("➕ Incluir no Plano"):
                    custo_base = dados_rec['total_cost']
                    st.session_state.fila_producao.append({
                        "nome": rec_sel,
                        "qtd": qtd,
                        "total_custo": custo_base * qtd,
                        "dados_receita": dados_rec
                    })
            else:
                st.warning("Sem receitas cadastradas.")

        # Tabela do Plano Atual
        if st.session_state.fila_producao:
            st.write("---")
            st.markdown("##### Fila Atual:")
            df_fila = pd.DataFrame(st.session_state.fila_producao)
            st.dataframe(
                df_fila[["qtd", "nome"]],
                use_container_width=True,
                hide_index=True
            )
            if st.button("🗑️ Limpar Plano"):
                st.session_state.fila_producao = []
                st.rerun()

    # --- 2. O QUE PRECISO? (RESULTADO) ---
    with col_resumo:
        if st.session_state.fila_producao:
            st.subheader("2. Materiais Necessários")
            
            # Custo Total
            total_custo = sum(i['total_custo'] for i in st.session_state.fila_producao)
            st.metric("Custo Total de Produção (Estimado)", f"R$ {total_custo:.2f}")
            
            st.divider()
            
            # CONSOLIDAR INGREDIENTES
            # Soma farinha com farinha, ovo com ovo, etc.
            lista_necessaria = {}
            
            for item in st.session_state.fila_producao:
                qtd_rec = item['qtd']
                for ing in item['dados_receita']['ingredients']:
                    nome = ing['nome']
                    total = ing['qtd_usada'] * qtd_rec
                    unidade = ing['unidade']
                    
                    if nome in lista_necessaria:
                        lista_necessaria[nome]['qtd'] += total
                    else:
                        lista_necessaria[nome] = {'qtd': total, 'unidade': unidade}
            
            # CRUZAR COM ESTOQUE
            estoque_real = pegar_estoque()
            tabela_final = []
            pode_produzir = True # Assume que sim até provar o contrário
            
            for nome_ing, dados in lista_necessaria.items():
                qtd_preciso = dados['qtd']
                
                # Busca no estoque
                item_est = next((e for e in estoque_real if e['nome'] == nome_ing), None)
                qtd_tenho = item_est['estoque_atual'] if item_est else 0
                
                falta = max(0, qtd_preciso - qtd_tenho)
                
                if falta > 0:
                    status = f"🔴 Faltam {falta:.0f}"
                    pode_produzir = False # Falta ingrediente, alerta visual (mas permitimos baixar igual se quiser)
                else:
                    status = "✅ Tenho"
                
                tabela_final.append({
                    "Ingrediente": nome_ing,
                    "Total Preciso": f"{qtd_preciso:.0f} {dados['unidade']}",
                    "Na Despensa": f"{qtd_tenho:.0f}",
                    "Status": status
                })
            
            # Exibe a Lista de Separação
            st.dataframe(pd.DataFrame(tabela_final), use_container_width=True, hide_index=True)
            
            st.caption("Esta tabela mostra o que você precisa separar ou comprar.")
            
            st.divider()
            
            # BOTÃO FINAL
            btn_label = "✅ Produzir e Baixar Estoque" if pode_produzir else "⚠️ Produzir mesmo faltando itens"
            tipo_btn = "primary" if pode_produzir else "secondary"
            
            if st.button(btn_label, type=tipo_btn):
                confirmar_producao(st.session_state.fila_producao)
                st.balloons()
                st.success("Produção registrada e estoque atualizado!")
                st.session_state.fila_producao = []
                st.rerun()
        
        else:
            st.info("👈 Adicione receitas ao lado para ver a lista de materiais aqui.")

# ==================================================
# ABA 2: RECEITAS (CRIAÇÃO)
# ==================================================
with aba_rec:
    if 'carrinho' not in st.session_state: st.session_state.carrinho = []
    
    c_new, c_list = st.columns(2)
    
    # Criar
    with c_new:
        st.subheader("Nova Ficha Técnica")
        with st.container(border=True):
            nom = st.text_input("Ingrediente (ex: Farinha)")
            c_p, c_t, c_u = st.columns(3)
            p_compra = c_p.number_input("Preço Pago (R$)", 0.0)
            p_tam = c_t.number_input("Tam. Pacote", 0.0)
            p_uso = c_u.number_input("Qtd Usada na Receita", 0.0)
            
            if st.button("Adicionar Item"):
                if p_tam > 0:
                    custo = (p_compra/p_tam)*p_uso
                    st.session_state.carrinho.append({
                        "nome": nom, "preco_compra": p_compra, "tam_pacote": p_tam,
                        "qtd_usada": p_uso, "unidade": "unid", "custo_final": custo
                    })
            
            if st.session_state.carrinho:
                st.dataframe(pd.DataFrame(st.session_state.carrinho)[['nome', 'qtd_usada']], use_container_width=True)
                with st.form("save"):
                    rn = st.text_input("Nome Receita")
                    ra = st.text_input("Autor")
                    if st.form_submit_button("Salvar Receita"):
                        salvar_receita(rn, ra, st.session_state.carrinho)
                        st.session_state.carrinho = []
                        st.success("Salvo!")
                        st.rerun()

    # Visualizar
    with c_list:
        st.subheader("Fichas Salvas")
        lista = pegar_receitas()
        if lista:
            sel = st.selectbox("Ver Detalhes", [r['name'] for r in lista])
            d = next(r for r in lista if r['name'] == sel)
            st.dataframe(pd.DataFrame(d['ingredients'])[['nome', 'qtd_usada', 'custo_final']], hide_index=True)
            st.caption(f"Custo Base da Receita: R$ {d['total_cost']:.2f}")
            if st.button("🗑️ Apagar"):
                doc = f"{d['name']}_{d['author']}".replace(" ", "_").lower()
                db.collection("recipes").document(doc).delete()
                st.rerun()

# ==================================================
# ABA 3: DESPENSA (ESTOQUE)
# ==================================================
with aba_est:
    st.subheader("📦 Minha Despensa")
    st.caption("Você pode ajustar manualmente se comprou mais coisas.")
    
    with st.expander("➕ Entrada Manual (Compras)"):
        ce1, ce2 = st.columns(2)
        ne = ce1.text_input("Item comprado")
        qe = ce2.number_input("Nova Quantidade Total que tenho", 0.0)
        if st.button("Atualizar Estoque"):
            sid = f"{ne}_generico".replace(" ", "_").lower()
            db.collection("inventory").document(sid).set({"nome": ne, "estoque_atual": qe}, merge=True)
            st.success("Atualizado")
            st.rerun()
            
    items = pegar_estoque()
    if items:
        # Mostra apenas o que tem saldo positivo para ficar limpo
        ativos = [i for i in items if i.get('estoque_atual', 0) > 0]
        if ativos:
            st.dataframe(pd.DataFrame(ativos)[['nome', 'estoque_atual']], use_container_width=True)
        else:
            st.info("Despensa vazia.")

# ==================================================
# ABA 4: HISTÓRICO
# ==================================================
with aba_hist:
    st.subheader("📜 Histórico de Produção")
    logs = db.collection("history").order_by("data", direction=firestore.Query.DESCENDING).stream()
    
    for l in logs:
        d = l.to_dict()
        dt = d['data'].strftime("%d/%m - %H:%M") if d.get('data') else ""
        custo = d.get('custo_total', 0)
        
        with st.expander(f"{dt} - Custo: R$ {custo:.2f}"):
            st.write(d.get('resumo', []))
