import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json
from datetime import datetime

# --- 1. CONFIGURAÇÃO VISUAL ---
st.set_page_config(
    page_title="Panela de Controle", 
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

def pegar_estoque():
    return [doc.to_dict() for doc in db.collection("inventory").stream()]

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
    
    # Atualiza referência de preço na despensa
    for item in ingredientes:
        safe_id = f"{item['nome']}_generico".replace(" ", "_").lower()
        db.collection("inventory").document(safe_id).set({
            "nome": item['nome'],
            "preco_ref": item['preco_compra'],
            "tam_ref": item['tam_pacote'],
            "unidade": item['unidade'],
            "ultimo_uso": firestore.SERVER_TIMESTAMP
        }, merge=True)

def confirmar_producao(fila_producao):
    estoque = pegar_estoque()
    for item in fila_producao:
        receita = item['dados_receita']
        qtd = item['qtd']
        for ing in receita['ingredients']:
            necessario = ing['qtd_usada'] * qtd
            nome = ing['nome']
            
            # Baixa Estoque
            item_est = next((e for e in estoque if e['nome'] == nome), None)
            if item_est:
                safe_id = f"{item_est['nome']}_generico".replace(" ", "_").lower()
                # CORREÇÃO AQUI: .get('estoque_atual', 0) para evitar erro
                atual = item_est.get('estoque_atual', 0)
                novo_saldo = max(0, atual - necessario)
                
                db.collection("inventory").document(safe_id).update({"estoque_atual": novo_saldo})
                item_est['estoque_atual'] = novo_saldo
                
    db.collection("history").add({
        "tipo": "Produção/Evento",
        "resumo": [f"{f['qtd']}x {f['nome']}" for f in fila_producao],
        "data": firestore.SERVER_TIMESTAMP,
        "custo_total": sum(f['total_custo'] for f in fila_producao),
        "faturamento": sum(f.get('total_venda', 0) for f in fila_producao)
    })
    return True

def zerar_estoque():
    docs = db.collection("inventory").stream()
    batch = db.batch()
    for doc in docs:
        ref = db.collection("inventory").document(doc.id)
        batch.update(ref, {"estoque_atual": 0})
    batch.commit()

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
c_head2.title("Panela de Controle")

with st.sidebar:
    st.caption("Admin")
    if st.text_input("Senha", type="password") != st.secrets.get("senha_app", "admin"):
        st.warning("🔒"); st.stop()

# ESTADO
if 'carrinho' not in st.session_state: st.session_state.carrinho = []
if 'fila_eventos' not in st.session_state: st.session_state.fila_eventos = []

# ABAS
aba_criar, aba_evento, aba_despensa, aba_diario = st.tabs([
    "📝 Criar Receitas", 
    "📊 Eventos & Lucro", 
    "📦 Despensa", 
    "📜 Diário"
])

# ==================================================
# ABA 1: CRIAR RECEITA
# ==================================================
with aba_criar:
    st.caption("Monte sua receita passo a passo.")
    
    col_input, col_preview = st.columns([1, 1.2])
    
    with col_input:
        with st.container(border=True):
            st.subheader("Novo Ingrediente")
            nome = st.text_input("Nome (ex: Leite)")
            
            c1, c2 = st.columns(2)
            p_compra = c1.number_input("Preço Pago (R$)", 0.0, format="%.2f")
            t_pacote = c2.number_input("Tamanho Pacote", 0.0)
            
            c3, c4 = st.columns(2)
            unid = c3.selectbox("Unid.", ["g", "ml", "unid", "kg", "L"])
            uso = c4.number_input("Qtd Usada", 0.0)
            
            if st.button("⬇️ Adicionar Item"):
                if t_pacote > 0:
                    custo = (p_compra / t_pacote) * uso
                    st.session_state.carrinho.append({
                        "nome": nome, "preco_compra": p_compra, "tam_pacote": t_pacote,
                        "unidade": unid, "qtd_usada": uso, "custo_final": custo
                    })
    
    with col_preview:
        st.subheader("Rascunho")
        if st.session_state.carrinho:
            df = pd.DataFrame(st.session_state.carrinho)
            st.dataframe(df[["nome", "qtd_usada", "custo_final"]], use_container_width=True, hide_index=True)
            
            custo_total = df['custo_final'].sum()
            cartao_financeiro("Custo da Receita", custo_total, "#FFF3E0", "#FF9800", "🏷️")
            
            with st.form("save"):
                n_rec = st.text_input("Nome do Prato")
                n_aut = st.text_input("Chef")
                if st.form_submit_button("💾 Salvar Receita"):
                    salvar_receita(n_rec, n_aut, st.session_state.carrinho)
                    st.balloons()
                    st.session_state.carrinho = []; st.rerun()
            
            if st.button("Limpar"):
                st.session_state.carrinho = []; st.rerun()
        else:
            # Lista receitas salvas para apagar
            with st.expander("Ver receitas salvas"):
                rec_list = pegar_receitas()
                if rec_list:
                    sel = st.selectbox("Receita", [r['name'] for r in rec_list])
                    sel_d = next(r for r in rec_list if r['name'] == sel)
                    if st.button("🗑️ Apagar"):
                        apagar_receita(sel_d['id']); st.rerun()

# ==================================================
# ABA 2: EVENTOS
# ==================================================
with aba_evento:
    st.caption("Planejador Financeiro de Eventos")
    
    c_plan, c_dash = st.columns([1, 1.5])
    
    with c_plan:
        with st.container(border=True):
            st.subheader("Planejar Produção")
            receitas = pegar_receitas()
            if receitas:
                r_sel = st.selectbox("Escolha o prato", [r['name'] for r in receitas])
                d_rec = next(r for r in receitas if r['name'] == r_sel)
                
                qtd_evt = st.number_input("Quantidade", 1, 5000, 10)
                
                # Sugestão de preço
                custo_base = d_rec['total_cost']
                venda_evt = st.number_input("Preço Venda (Unit)", value=custo_base*3.0, format="%.2f")
                
                if st.button("➕ Adicionar"):
                    st.session_state.fila_eventos.append({
                        "nome": r_sel, "qtd": qtd_evt, "total_custo": custo_base*qtd_evt,
                        "total_venda": venda_evt*qtd_evt, "dados_receita": d_rec
                    })
        
        if st.session_state.fila_eventos:
            if st.button("Limpar Lista"):
                st.session_state.fila_eventos = []; st.rerun()

    with c_dash:
        if st.session_state.fila_eventos:
            st.subheader("📊 Resultado Financeiro")
            
            custo_tot = sum(x['total_custo'] for x in st.session_state.fila_eventos)
            venda_tot = sum(x['total_venda'] for x in st.session_state.fila_eventos)
            lucro = venda_tot - custo_tot
            margem = (lucro/venda_tot)*100 if venda_tot > 0 else 0
            
            # --- CARTÕES COLORIDOS ---
            col_c, col_f, col_l = st.columns(3)
            
            with col_c:
                cartao_financeiro("Custo Total", custo_tot, "#FFEBEE", "#D32F2F", "🔴")
            
            with col_f:
                cartao_financeiro("Faturamento", venda_tot, "#E3F2FD", "#1976D2", "🔵")
                
            with col_l:
                cor_bg = "#E8F5E9" if lucro >= 0 else "#FFEBEE"
                cor_tx = "#388E3C" if lucro >= 0 else "#D32F2F"
                cartao_financeiro("Lucro Líquido", lucro, cor_bg, cor_tx, "🤑")

            st.caption(f"Margem de Lucro: {margem:.1f}%")
            if margem > 0:
                st.progress(min(int(margem), 100))
            else:
                st.warning("Prejuízo estimado!")

            st.divider()
            
            # Lista de Compras
            st.subheader("🛒 Lista de Compras")
            lista_nec = {}
            for item in st.session_state.fila_eventos:
                q = item['qtd']
                for i in item['dados_receita']['ingredients']:
                    lista_nec[i['nome']] = lista_nec.get(i['nome'], 0) + (i['qtd_usada']*q)
            
            estoque = pegar_estoque()
            tab_compra = []
            tudo_ok = True
            
            for nome, qtd in lista_nec.items():
                e_item = next((e for e in estoque if e['nome'] == nome), None)
                # CORREÇÃO CRÍTICA AQUI: .get('estoque_atual', 0)
                tem = e_item.get('estoque_atual', 0) if e_item else 0
                
                falta = max(0, qtd - tem)
                status = "✅ Ok" if falta == 0 else f"❌ Falta {falta:.0f}"
                tab_compra.append({"Item": nome, "Preciso": qtd, "Tenho": tem, "Status": status})
                if falta > 0: tudo_ok = False
            
            st.dataframe(pd.DataFrame(tab_compra), use_container_width=True, hide_index=True)
            
            # Botão Produzir
            txt_btn = "🚀 Confirmar Produção (Baixar Estoque)" if tudo_ok else "⚠️ Produzir com Falta de Itens"
            type_btn = "primary" if tudo_ok else "secondary"
            
            if st.button(txt_btn, type=type_btn):
                confirmar_producao(st.session_state.fila_eventos)
                st.balloons(); st.success("Registrado!"); st.session_state.fila_eventos = []; st.rerun()
        else:
            st.info("👈 Adicione itens ao planejamento.")

# ==================================================
# ABA 3: DESPENSA
# ==================================================
with aba_despensa:
    st.subheader("📦 Despensa")
    c_btn1, c_btn2 = st.columns([4, 1])
    with c_btn2:
        if st.button("🗑️ Zerar Tudo"):
            zerar_estoque(); st.warning("Zerado!"); st.rerun()
    
    with st.expander("➕ Compra Manual"):
        cx1, cx2 = st.columns(2)
        ni = cx1.text_input("Item")
        qi = cx2.number_input("Qtd", 0.0)
        if st.button("Salvar") and ni:
            sid = f"{ni}_generico".replace(" ", "_").lower()
            db.collection("inventory").document(sid).set({"nome": ni, "estoque_atual": qi}, merge=True)
            st.success("Salvo!"); st.rerun()
            
    items = pegar_estoque()
    if items:
        # Usa .get() para evitar erro se o campo não existir
        validos = [i for i in items if i.get('estoque_atual', 0) > 0]
        if validos:
            st.dataframe(pd.DataFrame(validos)[['nome', 'estoque_atual']], use_container_width=True)
        else:
            st.info("Vazio.")

# ==================================================
# ABA 4: DIÁRIO
# ==================================================
with aba_diario:
    st.subheader("📜 Histórico")
    logs = db.collection("history").order_by("data", direction=firestore.Query.DESCENDING).stream()
    for l in logs:
        d = l.to_dict()
        dt = d['data'].strftime("%d/%m %H:%M") if d.get('data') else "-"
        lucro_hist = d.get('faturamento',0) - d.get('custo_total',0)
        
        with st.expander(f"{dt} | Lucro: R$ {lucro_hist:.2f}"):
            st.write(d.get('resumo', []))
            st.markdown(f"**Venda:** R$ {d.get('faturamento',0):.2f} | **Custo:** R$ {d.get('custo_total',0):.2f}")

