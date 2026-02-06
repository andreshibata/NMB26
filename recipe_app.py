import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json
from datetime import datetime

# --- 1. CONFIGURAÇÃO VISUAL ---
st.set_page_config(
    page_title="Gestor de Lucro & Produção", 
    layout="wide", 
    page_icon="💰",
    initial_sidebar_state="collapsed"
)

# Estilo para destacar o Lucro
st.markdown("""
    <style>
    .stMetric { background-color: #f0f2f6; border-radius: 8px; padding: 10px; border: 1px solid #dee2e6; }
    div[data-testid="stMetricValue"] { font-size: 24px; }
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

# --- 3. LÓGICA DE DADOS ---

def pegar_receitas():
    docs = db.collection("recipes").stream()
    lista = []
    for doc in docs:
        d = doc.to_dict()
        d['id'] = doc.id
        lista.append(d)
    return lista

def pegar_estoque():
    return [doc.to_dict() for doc in db.collection("inventory").stream()]

def zerar_estoque_mantendo_precos():
    """Define a quantidade de todos os itens para 0, mas mantém o cadastro"""
    docs = db.collection("inventory").stream()
    batch = db.batch()
    for doc in docs:
        ref = db.collection("inventory").document(doc.id)
        batch.update(ref, {"estoque_atual": 0})
    batch.commit()

def salvar_receita(nome, autor, ingredientes, doc_id=None):
    if not doc_id:
        doc_id = f"{nome}_{autor}".replace(" ", "_").lower()
    
    custo = sum(i['custo_final'] for i in ingredientes)
    
    db.collection("recipes").document(doc_id).set({
        "name": nome,
        "author": autor,
        "ingredients": ingredientes,
        "total_cost": custo,
        "updated_at": firestore.SERVER_TIMESTAMP
    }, merge=True)
    
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

def apagar_receita(doc_id):
    db.collection("recipes").document(doc_id).delete()

def atualizar_estoque_lote(df_editado):
    for index, row in df_editado.iterrows():
        safe_id = f"{row['nome']}_generico".replace(" ", "_").lower()
        db.collection("inventory").document(safe_id).set({
            "nome": row['nome'],
            "estoque_atual": row['estoque_atual'],
            "preco_ref": row['preco_ref'],
            "tam_ref": row['tam_ref']
        }, merge=True)

def confirmar_producao(fila_producao):
    estoque = pegar_estoque()
    for item in fila_producao:
        receita = item['dados_receita']
        qtd = item['qtd']
        for ing in receita['ingredients']:
            necessario = ing['qtd_usada'] * qtd
            nome = ing['nome']
            item_est = next((e for e in estoque if e['nome'] == nome), None)
            if item_est:
                safe_id = f"{item_est['nome']}_generico".replace(" ", "_").lower()
                novo = max(0, item_est.get('estoque_atual', 0) - necessario)
                db.collection("inventory").document(safe_id).update({"estoque_atual": novo})
                item_est['estoque_atual'] = novo
                
    db.collection("history").add({
        "tipo": "Produção",
        "resumo": [f"{f['qtd']}x {f['nome']}" for f in fila_producao],
        "data": firestore.SERVER_TIMESTAMP,
        "custo_total": sum(f['total_custo'] for f in fila_producao),
        "faturamento_previsto": sum(f.get('total_venda', 0) for f in fila_producao)
    })
    return True

# --- 4. INTERFACE ---

c1, c2 = st.columns([1, 10])
c1.title("💸")
c2.title("Gestor de Produção & Margem")

with st.sidebar:
    if st.text_input("Senha Admin", type="password") != st.secrets.get("senha_app", "admin"):
        st.warning("🔒"); st.stop()

# ESTADOS
if 'fila_prod' not in st.session_state: st.session_state.fila_prod = []
if 'editor_receita' not in st.session_state: st.session_state.editor_receita = []

# ABAS
aba_plan, aba_rec, aba_est, aba_hist = st.tabs([
    "🚀 Planejar (Margem)", 
    "📖 Receitas", 
    "📦 Despensa", 
    "📜 Histórico"
])

# ==================================================
# ABA 1: PLANEJADOR FINANCEIRO
# ==================================================
with aba_plan:
    st.caption("Planeje sua produção, defina o preço de venda e veja se vai dar lucro.")
    
    col_in, col_out = st.columns([1, 1.6])
    
    # --- ESQUERDA: ADICIONAR ITEM ---
    with col_in:
        with st.container(border=True):
            st.subheader("O que vamos produzir?")
            receitas = pegar_receitas()
            
            if receitas:
                r_sel = st.selectbox("Receita", [r['name'] for r in receitas])
                dados_r = next(r for r in receitas if r['name'] == r_sel)
                custo_base = dados_r['total_cost']
                
                c_q, c_v = st.columns(2)
                qtd = c_q.number_input("Quantidade", 1, 1000, 10)
                # Sugestão inteligente: 3x o custo
                sugestao = custo_base * 3
                preco_venda = c_v.number_input("Preço Venda (Unit)", value=sugestao, min_value=0.0, format="%.2f")
                
                if st.button("➕ Adicionar ao Plano"):
                    custo_total = custo_base * qtd
                    venda_total = preco_venda * qtd
                    
                    st.session_state.fila_prod.append({
                        "nome": r_sel, 
                        "qtd": qtd, 
                        "custo_unit": custo_base,
                        "venda_unit": preco_venda,
                        "total_custo": custo_total, 
                        "total_venda": venda_total,
                        "dados_receita": dados_r
                    })
        
        # Lista simples do que foi adicionado
        if st.session_state.fila_prod:
            st.write("---")
            for idx, item in enumerate(st.session_state.fila_prod):
                col_txt, col_del = st.columns([4, 1])
                col_txt.text(f"{item['qtd']}x {item['nome']} (Venda: R${item['venda_unit']:.2f})")
                if col_del.button("❌", key=f"del_q_{idx}"):
                    st.session_state.fila_prod.pop(idx)
                    st.rerun()
            
            if st.button("Limpar Tudo"): 
                st.session_state.fila_prod = []; st.rerun()

    # --- DIREITA: DASHBOARD DE LUCRO ---
    with col_out:
        if st.session_state.fila_prod:
            st.subheader("📊 Análise Financeira do Evento")
            
            # CÁLCULOS TOTAIS
            tot_custo = sum(x['total_custo'] for x in st.session_state.fila_prod)
            tot_venda = sum(x['total_venda'] for x in st.session_state.fila_prod)
            lucro = tot_venda - tot_custo
            margem = (lucro / tot_venda * 100) if tot_venda > 0 else 0
            
            # MÉTRICAS
            m1, m2, m3 = st.columns(3)
            m1.metric("Custo Produção", f"R$ {tot_custo:.2f}")
            m2.metric("Faturamento", f"R$ {tot_venda:.2f}")
            m3.metric("Lucro Líquido", f"R$ {lucro:.2f}", f"{margem:.1f}%")
            
            if margem < 30:
                st.warning("⚠️ Margem baixa! Considere aumentar o preço de venda.")
            
            st.divider()
            
            # MATERIAIS
            st.subheader("🛒 Lista de Materiais")
            
            # Consolida ingredientes
            lista = {}
            for item in st.session_state.fila_prod:
                q = item['qtd']
                for ing in item['dados_receita']['ingredients']:
                    nome = ing['nome']
                    nec = ing['qtd_usada'] * q
                    lista[nome] = lista.get(nome, 0) + nec
            
            estoque = pegar_estoque()
            tabela = []
            pode_produzir = True
            
            for nome, qtd_nec in lista.items():
                item_est = next((e for e in estoque if e['nome'] == nome), None)
                qtd_tem = item_est['estoque_atual'] if item_est else 0
                falta = max(0, qtd_nec - qtd_tenho)
                
                status = f"🔴 Falta {falta:.0f}" if falta > 0 else "✅ Ok"
                tabela.append({
                    "Item": nome,
                    "Necessário": f"{qtd_nec:.0f}",
                    "Estoque": f"{qtd_tenho:.0f}",
                    "Status": status
                })
                if falta > 0: pode_produzir = False
            
            st.dataframe(pd.DataFrame(tabela), use_container_width=True, hide_index=True)
            
            # AÇÃO FINAL
            btn_txt = "🚀 Produzir (Baixar Estoque)" if pode_produzir else "⚠️ Produzir mesmo com falta"
            btn_type = "primary" if pode_produzir else "secondary"
            
            if st.button(btn_txt, type=btn_type):
                confirmar_producao(st.session_state.fila_prod)
                st.balloons()
                st.success("Produção registrada! Estoque baixado e histórico salvo.")
                st.session_state.fila_prod = []
                st.rerun()
        else:
            st.info("👈 Comece adicionando receitas para ver o cálculo de margem.")

# ==================================================
# ABA 2: RECEITAS (EDITOR)
# ==================================================
with aba_rec:
    modo = st.radio("Ação", ["Criar Nova", "Editar Existente"], horizontal=True)
    
    if modo == "Criar Nova":
        if 'novo_carrinho' not in st.session_state: st.session_state.novo_carrinho = []
        c_form, c_view = st.columns(2)
        with c_form:
            with st.container(border=True):
                n = st.text_input("Ingrediente", key="n_n")
                c1, c2, c3 = st.columns(3)
                p = c1.number_input("Preço", 0.0, key="p_n")
                t = c2.number_input("Pacote", 0.0, key="t_n")
                u = c3.number_input("Qtd Usada", 0.0, key="u_n")
                if st.button("Add") and t > 0:
                    st.session_state.novo_carrinho.append({
                        "nome": n, "preco_compra": p, "tam_pacote": t, 
                        "qtd_usada": u, "unidade": "unid", "custo_final": (p/t)*u
                    })
        with c_view:
            if st.session_state.novo_carrinho:
                st.dataframe(pd.DataFrame(st.session_state.novo_carrinho))
                with st.form("sv"):
                    if st.form_submit_button("Salvar"):
                        salvar_receita(st.text_input("Nome"), st.text_input("Autor"), st.session_state.novo_carrinho)
                        st.session_state.novo_carrinho = []; st.success("Ok!"); st.rerun()

    else: # Editar
        receitas = pegar_receitas()
        if receitas:
            sel = st.selectbox("Editar qual?", [r['name'] for r in receitas])
            orig = next(r for r in receitas if r['name'] == sel)
            if st.button("Carregar"):
                st.session_state.editor_receita = orig['ingredients']
                st.session_state.editor_id = orig['id']
                st.session_state.editor_autor = orig['author']
                st.rerun()
            
            if 'editor_id' in st.session_state and st.session_state.editor_id == orig['id']:
                st.divider()
                # Adicionar novo item na edição
                with st.expander("➕ Adicionar Item"):
                    cn1, cn2, cn3, cn4 = st.columns(4)
                    new_n = cn1.text_input("Nome", key="ed_n")
                    new_p = cn2.number_input("Preço", key="ed_p")
                    new_t = cn3.number_input("Pacote", key="ed_t")
                    new_u = cn4.number_input("Uso", key="ed_u")
                    if st.button("Inserir") and new_t > 0:
                        st.session_state.editor_receita.append({
                            "nome": new_n, "preco_compra": new_p, "tam_pacote": new_t,
                            "qtd_usada": new_u, "unidade": "unid", "custo_final": (new_p/new_t)*new_u
                        }); st.rerun()
                
                df_ed = st.data_editor(pd.DataFrame(st.session_state.editor_receita), num_rows="dynamic", key="data_editor_rec")
                
                if st.button("💾 Salvar Alterações"):
                    nova_lista = []
                    for idx, row in df_ed.iterrows():
                        if row['qtd_usada'] > 0:
                            row['custo_final'] = (row['preco_compra']/row['tam_pacote'])*row['qtd_usada']
                            nova_lista.append(row.to_dict())
                    salvar_receita(sel, st.session_state.editor_autor, nova_lista, st.session_state.editor_id)
                    st.success("Atualizado!")
                
                if st.button("🗑️ Apagar Receita"):
                    apagar_receita(st.session_state.editor_id)
                    st.rerun()

# ==================================================
# ABA 3: DESPENSA (ZERAR E EDITAR)
# ==================================================
with aba_est:
    c_tit, c_act = st.columns([4, 1])
    c_tit.subheader("📦 Estoque")
    
    # BOTÃO ZERAR ESTOQUE (NOVO!)
    with c_act:
        if st.button("🗑️ Zerar Todo Estoque", type="primary", help="Define a quantidade de todos os itens para 0"):
            zerar_estoque_mantendo_precos()
            st.warning("Estoque zerado! (Preços mantidos)")
            st.rerun()
    
    st.caption("Edite os valores na tabela abaixo.")
    
    estoque = pegar_estoque()
    if estoque:
        df_est = pd.DataFrame(estoque)
        cols = ["nome", "estoque_atual", "preco_ref", "tam_ref"]
        # Garante colunas
        for c in cols: 
            if c not in df_est.columns: df_est[c] = 0
            
        editor = st.data_editor(
            df_est[cols], 
            column_config={
                "nome": st.column_config.TextColumn("Item", disabled=True),
                "estoque_atual": st.column_config.NumberColumn("Qtd Atual"),
                "preco_ref": st.column_config.NumberColumn("Preço Ref (R$)"),
                "tam_ref": st.column_config.NumberColumn("Pacote Ref")
            },
            use_container_width=True,
            hide_index=True
        )
        
        if st.button("💾 Salvar Alterações na Despensa"):
            atualizar_estoque_lote(editor)
            st.success("Salvo!")
            st.rerun()
    else:
        st.info("Vazio.")

# ==================================================
# ABA 4: HISTÓRICO
# ==================================================
with aba_hist:
    st.subheader("📜 Histórico")
    logs = db.collection("history").order_by("data", direction=firestore.Query.DESCENDING).stream()
    for l in logs:
        d = l.to_dict()
        dt = d['data'].strftime("%d/%m %H:%M") if d.get('data') else ""
        fat = d.get('faturamento_previsto', 0)
        custo = d.get('custo_total', 0)
        lucro = fat - custo
        
        with st.expander(f"{dt} | Lucro Est: R$ {lucro:.2f}"):
            st.write(d.get('resumo', []))
            st.caption(f"Faturamento: R$ {fat:.2f} | Custo: R$ {custo:.2f}")

