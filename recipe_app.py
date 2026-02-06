import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json
from datetime import datetime

# --- 1. CONFIGURAÇÃO VISUAL CASUAL ---
st.set_page_config(
    page_title="Panela de Controle", 
    layout="wide", 
    page_icon="🥘",
    initial_sidebar_state="collapsed"
)

# CSS para deixar amigável (Botões redondos, cores suaves)
st.markdown("""
    <style>
    .stButton>button { border-radius: 20px; font-weight: bold; }
    .stMetric { background-color: #f7f7f7; border-radius: 15px; padding: 10px; border: 1px solid #eee; }
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

# --- 3. LÓGICA (O CÉREBRO) ---

def pegar_receitas():
    # Retorna lista com IDs para edição
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
    
    # Salva preços de referência na despensa (para o futuro)
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
            
            # Busca e desconta do estoque
            item_est = next((e for e in estoque if e['nome'] == nome), None)
            if item_est:
                safe_id = f"{item_est['nome']}_generico".replace(" ", "_").lower()
                novo_saldo = max(0, item_est.get('estoque_atual', 0) - necessario)
                db.collection("inventory").document(safe_id).update({"estoque_atual": novo_saldo})
                item_est['estoque_atual'] = novo_saldo # Atualiza localmente
                
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

# --- 4. INTERFACE ---

c_tit1, c_tit2 = st.columns([1, 8])
c_tit1.markdown("# 🥘")
c_tit2.title("Panela de Controle")

# Login Discreto
with st.sidebar:
    st.caption("Admin Area")
    if st.text_input("Senha", type="password") != st.secrets.get("senha_app", "admin"):
        st.warning("🔒")
        st.stop()

# ESTADO
if 'carrinho' not in st.session_state: st.session_state.carrinho = []
if 'fila_eventos' not in st.session_state: st.session_state.fila_eventos = []

# ABAS AMIGÁVEIS
aba_criar, aba_evento, aba_despensa, aba_diario = st.tabs([
    "📝 Criar Receitas", 
    "🎉 Eventos & Margem", 
    "📦 Despensa", 
    "📜 Diário"
])

# ==================================================
# ABA 1: CRIAR (INPUT CLÁSSICO - CASUAL)
# ==================================================
with aba_criar:
    st.caption("Adicione os ingredientes como se estivesse lendo a embalagem.")
    
    col_form, col_lista = st.columns([1, 1.2])
    
    # --- FORMULÁRIO (Igual à Versão 1) ---
    with col_form:
        with st.container(border=True):
            st.subheader("Novo Ingrediente")
            
            nome_ing = st.text_input("Nome do Ingrediente", placeholder="Ex: Farinha de Trigo")
            
            # Linha de Preços e Tamanho (A Lógica original)
            c1, c2 = st.columns(2)
            preco_pago = c1.number_input("Preço Pago (R$)", min_value=0.0, format="%.2f")
            tam_pacote = c2.number_input("Tamanho Pacote", min_value=0.0)
            
            # Linha de Uso
            c3, c4 = st.columns(2)
            unidade = c3.selectbox("Unidade", ["g", "ml", "unid", "kg", "L"])
            qtd_usada = c4.number_input("Qtd. Usada na Receita", min_value=0.0)
            
            if st.button("⬇️ Colocar na Receita", type="primary"):
                if nome_ing and tam_pacote > 0:
                    custo_final = (preco_pago / tam_pacote) * qtd_usada
                    st.session_state.carrinho.append({
                        "nome": nome_ing,
                        "preco_compra": preco_pago,
                        "tam_pacote": tam_pacote,
                        "unidade": unidade,
                        "qtd_usada": qtd_usada,
                        "custo_final": custo_final
                    })
                else:
                    st.toast("Preencha o nome e tamanho do pacote!", icon="⚠️")

    # --- LISTA DE INGREDIENTES ---
    with col_lista:
        st.subheader("Rascunho da Receita")
        
        if st.session_state.carrinho:
            df = pd.DataFrame(st.session_state.carrinho)
            # Mostra tabelinha limpa
            st.dataframe(
                df[["nome", "qtd_usada", "unidade", "custo_final"]],
                use_container_width=True,
                hide_index=True
            )
            
            custo_total = df['custo_final'].sum()
            st.metric("Custo Total da Receita", f"R$ {custo_total:.2f}")
            
            st.divider()
            
            with st.form("salvar_receita"):
                c_nome, c_autor = st.columns(2)
                r_nome = c_nome.text_input("Nome do Prato")
                r_autor = c_autor.text_input("Chef (Autor)")
                
                if st.form_submit_button("💾 Salvar no Caderno"):
                    if r_nome:
                        salvar_receita(r_nome, r_autor, st.session_state.carrinho)
                        st.balloons()
                        st.session_state.carrinho = []
                        st.rerun()
                    else:
                        st.error("Dê um nome para a receita.")
            
            if st.button("Limpar Rascunho"):
                st.session_state.carrinho = []
                st.rerun()
        else:
            st.info("Adicione ingredientes ao lado para começar.")
            
            # Área para ver/apagar receitas existentes (simplificada)
            with st.expander("Ver receitas salvas"):
                receitas = pegar_receitas()
                if receitas:
                    sel = st.selectbox("Selecione", [r['name'] for r in receitas])
                    rec_sel = next(r for r in receitas if r['name'] == sel)
                    st.dataframe(pd.DataFrame(rec_sel['ingredients'])[['nome', 'qtd_usada']])
                    if st.button("🗑️ Apagar Receita"):
                        apagar_receita(rec_sel['id'])
                        st.rerun()

# ==================================================
# ABA 2: EVENTOS & MARGEM (O PLANEJADOR)
# ==================================================
with aba_evento:
    st.caption("Vai fazer um evento? Planeje aqui a produção, veja o lucro e a lista de compras.")
    
    c_plan, c_resumo = st.columns([1, 1.5])
    
    with c_plan:
        with st.container(border=True):
            st.subheader("Adicionar ao Evento")
            receitas = pegar_receitas()
            
            if receitas:
                r_escolha = st.selectbox("Qual receita?", [r['name'] for r in receitas])
                dados_r = next(r for r in receitas if r['name'] == r_escolha)
                custo_base = dados_r['total_cost']
                
                # Inputs de Planejamento
                q_evt = st.number_input("Quantidade", 1, 1000, 10)
                v_evt = st.number_input("Preço de Venda (Unidade)", value=custo_base*3.0, format="%.2f")
                
                if st.button("➕ Incluir"):
                    st.session_state.fila_eventos.append({
                        "nome": r_escolha,
                        "qtd": q_evt,
                        "custo_unit": custo_base,
                        "venda_unit": v_evt,
                        "total_custo": custo_base * q_evt,
                        "total_venda": v_evt * q_evt,
                        "dados_receita": dados_r
                    })
    
        if st.session_state.fila_eventos:
            if st.button("Limpar Planejamento"):
                st.session_state.fila_eventos = []; st.rerun()

    with c_resumo:
        if st.session_state.fila_eventos:
            st.subheader("📊 Resumo Financeiro")
            
            total_custo = sum(i['total_custo'] for i in st.session_state.fila_eventos)
            total_venda = sum(i['total_venda'] for i in st.session_state.fila_eventos)
            lucro = total_venda - total_custo
            margem = (lucro / total_venda * 100) if total_venda > 0 else 0
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Custo Estimado", f"R$ {total_custo:.2f}")
            m2.metric("Faturamento", f"R$ {total_venda:.2f}")
            m3.metric("Lucro Líquido", f"R$ {lucro:.2f}", f"{margem:.1f}%")
            
            st.divider()
            
            st.subheader("🛒 Lista de Compras / Separação")
            
            # Consolida Lista
            lista_nec = {}
            for item in st.session_state.fila_eventos:
                q = item['qtd']
                for ing in item['dados_receita']['ingredients']:
                    nome = ing['nome']
                    total = ing['qtd_usada'] * q
                    lista_nec[nome] = lista_nec.get(nome, 0) + total
            
            estoque = pegar_estoque()
            tabela_compras = []
            tudo_ok = True
            
            for nome, qtd_preciso in lista_nec.items():
                # Verifica estoque
                item_est = next((e for e in estoque if e['nome'] == nome), None)
                qtd_tenho = item_est['estoque_atual'] if item_est else 0
                falta = max(0, qtd_preciso - qtd_tenho)
                
                status = "✅ Tenho" if falta == 0 else f"❌ Falta {falta:.0f}"
                tabela_compras.append({
                    "Ingrediente": nome,
                    "Preciso": f"{qtd_preciso:.0f}",
                    "Tenho": f"{qtd_tenho:.0f}",
                    "Status": status
                })
                if falta > 0: tudo_ok = False
            
            st.dataframe(pd.DataFrame(tabela_compras), use_container_width=True, hide_index=True)
            
            # Botão Produzir
            st.caption("Ao clicar abaixo, os ingredientes serão descontados da despensa.")
            texto_btn = "🚀 Produzir e Baixar Estoque" if tudo_ok else "⚠️ Produzir com itens faltando"
            cor_btn = "primary" if tudo_ok else "secondary"
            
            if st.button(texto_btn, type=cor_btn):
                confirmar_producao(st.session_state.fila_eventos)
                st.balloons()
                st.success("Produção registrada com sucesso!")
                st.session_state.fila_eventos = []
                st.rerun()
        else:
            st.info("Planeje seu evento na esquerda para ver os cálculos aqui.")

# ==================================================
# ABA 3: DESPENSA
# ==================================================
with aba_despensa:
    st.subheader("📦 O que tenho em casa")
    
    col_view, col_action = st.columns([4, 1])
    
    with col_action:
        if st.button("🗑️ Zerar Estoque", help="Define todas as quantidades como 0, mas mantém os preços."):
            zerar_estoque()
            st.warning("Despensa esvaziada!")
            st.rerun()
            
    # Entrada manual rápida
    with st.expander("➕ Ajuste Manual (Adicionar Compras)"):
        ce1, ce2 = st.columns(2)
        ne = ce1.text_input("Item")
        qe = ce2.number_input("Nova Quantidade Total", 0.0)
        if st.button("Atualizar Item"):
            sid = f"{ne}_generico".replace(" ", "_").lower()
            # Salva mantendo campos existentes se houver
            db.collection("inventory").document(sid).set({"nome": ne, "estoque_atual": qe}, merge=True)
            st.success("Salvo!")
            st.rerun()

    items = pegar_estoque()
    if items:
        # Mostra apenas o que tem quantidade > 0 para ficar limpo
        ativos = [i for i in items if i.get('estoque_atual', 0) > 0]
        if ativos:
            df_est = pd.DataFrame(ativos)
            st.dataframe(df_est[['nome', 'estoque_atual']], use_container_width=True, hide_index=True)
        else:
            st.info("Despensa está zerada.")

# ==================================================
# ABA 4: DIÁRIO
# ==================================================
with aba_diario:
    st.subheader("📜 Histórico")
    logs = db.collection("history").order_by("data", direction=firestore.Query.DESCENDING).stream()
    
    for l in logs:
        d = l.to_dict()
        dt = d['data'].strftime("%d/%m - %H:%M") if d.get('data') else "-"
        fat = d.get('faturamento', 0)
        custo = d.get('custo_total', 0)
        lucro = fat - custo
        
        with st.expander(f"{dt} | Lucro: R$ {lucro:.2f}"):
            st.write(d.get('resumo', []))
            st.caption(f"Venda: R$ {fat:.2f} | Custo: R$ {custo:.2f}")
