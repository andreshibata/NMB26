import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json
from datetime import datetime

# --- 1. CONFIGURAÇÃO VISUAL (CASUAL & PRO) ---
st.set_page_config(
    page_title="Gestor de Receitas & Eventos", 
    layout="wide", 
    page_icon="🍳",
    initial_sidebar_state="collapsed"
)

# CSS para deixar bonito e esconder complexidade visual desnecessária
st.markdown("""
    <style>
    .stButton>button { border-radius: 12px; }
    .stMetric { background-color: #f0f2f6; padding: 10px; border-radius: 10px; }
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

# --- 3. LÓGICA DO SISTEMA ---

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
    
    # SALVAMENTO INTELIGENTE: Atualiza preços de referência no estoque
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

def registrar_evento(receita_nome, qtd_vendida):
    """Baixa do estoque e registra histórico"""
    receitas = pegar_receitas()
    rec = next((r for r in receitas if r['name'] == receita_nome), None)
    if not rec: return False
    
    estoque = pegar_estoque()
    log = []
    
    # Tenta baixar do estoque (Simples: Primeiro que encontrar)
    for ing in rec['ingredients']:
        necessario = ing['qtd_usada'] * qtd_vendida
        nome = ing['nome']
        
        # Acha item no estoque
        item_est = next((e for e in estoque if e['nome'] == nome and e.get('estoque_atual', 0) > 0), None)
        
        if item_est:
            safe_id = f"{item_est['nome']}_generico".replace(" ", "_").lower()
            novo_saldo = max(0, item_est['estoque_atual'] - necessario)
            db.collection("inventory").document(safe_id).update({"estoque_atual": novo_saldo})
            log.append(f"✅ {nome}: Baixado {necessario:.0f}{ing['unidade']}")
        else:
            log.append(f"⚠️ {nome}: Sem estoque registrado (apenas contabilizado).")

    # Salva no Histórico
    db.collection("history").add({
        "receita": receita_nome,
        "qtd": qtd_vendida,
        "data": firestore.SERVER_TIMESTAMP,
        "tipo": "Evento/Venda"
    })
    return True

# --- 4. INTERFACE ---

# Cabeçalho
c1, c2 = st.columns([1, 8])
c1.title("🥘")
c2.title("Gestor de Receitas & Eventos")

# Login Discreto
with st.sidebar:
    st.header("Admin")
    if st.text_input("Senha", type="password") != st.secrets.get("senha_app", "admin"):
        st.warning("🔒")
        st.stop()

# Abas Híbridas (Casual + Controle)
aba_caderno, aba_evento, aba_estoque, aba_historico = st.tabs([
    "📖 Receitas & Preços", 
    "🎉 Realizar Evento", 
    "📦 Meu Estoque", 
    "📅 Histórico"
])

# ==================================================
# ABA 1: RECEITAS (CRIAÇÃO + MARGEM)
# ==================================================
with aba_caderno:
    if 'carrinho' not in st.session_state: st.session_state.carrinho = []
    
    col_criar, col_ver = st.columns([1, 1.2])
    
    # --- LADO ESQUERDO: CRIAR ---
    with col_criar:
        st.subheader("✨ Nova Receita")
        with st.container(border=True):
            nom = st.text_input("Ingrediente")
            c_p, c_t, c_u = st.columns(3)
            p_compra = c_p.number_input("Preço (R$)", 0.0, format="%.2f")
            p_tam = c_t.number_input("Pacote", 0.0)
            p_uso = c_u.number_input("Qtd Usada", 0.0)
            
            if st.button("Adicionar"):
                if p_tam > 0:
                    custo = (p_compra / p_tam) * p_uso
                    st.session_state.carrinho.append({
                        "nome": nom, "preco_compra": p_compra, "tam_pacote": p_tam, 
                        "qtd_usada": p_uso, "unidade": "unid", "custo_final": custo
                    })

            if st.session_state.carrinho:
                st.divider()
                df = pd.DataFrame(st.session_state.carrinho)
                st.dataframe(df[["nome", "custo_final"]], use_container_width=True, hide_index=True)
                st.caption(f"Custo Total: R$ {df['custo_final'].sum():.2f}")
                
                with st.form("salvar"):
                    r_nome = st.text_input("Nome da Receita")
                    r_autor = st.text_input("Autor")
                    if st.form_submit_button("💾 Salvar Receita"):
                        salvar_receita(r_nome, r_autor, st.session_state.carrinho)
                        st.success("Salvo!")
                        st.session_state.carrinho = []
                        st.rerun()

    # --- LADO DIREITO: VER E CALCULAR MARGEM ---
    with col_ver:
        st.subheader("💰 Consultar Preços e Margem")
        receitas = pegar_receitas()
        
        if receitas:
            rec_sel = st.selectbox("Selecione uma receita para analisar:", [r['name'] for r in receitas])
            dados = next(r for r in receitas if r['name'] == rec_sel)
            
            # CARD DE DETALHES
            with st.expander(f"Detalhes: {dados['name']} (Custo: R$ {dados['total_cost']:.2f})", expanded=True):
                # 1. Ingredientes
                st.dataframe(pd.DataFrame(dados['ingredients'])[["nome", "qtd_usada", "custo_final"]], use_container_width=True)
                
                st.divider()
                st.markdown("### 📊 Calculadora de Evento")
                
                # 2. Calculadora de Margem
                c_custo, c_venda, c_lucro = st.columns(3)
                
                custo = dados['total_cost']
                c_custo.metric("Custo de Produção", f"R$ {custo:.2f}")
                
                # Input interativo
                preco_venda = c_venda.number_input("Preço de Venda (Unidade)", value=custo*2.5, step=1.0)
                
                if preco_venda > 0:
                    lucro = preco_venda - custo
                    margem = (lucro / preco_venda) * 100
                    
                    c_lucro.metric("Lucro Líquido", f"R$ {lucro:.2f}", f"{margem:.0f}% Margem")
                    
                    if margem < 30:
                        st.warning("⚠️ Margem baixa para eventos.")
                    elif margem > 50:
                        st.success("✅ Margem saudável!")
                
                # Botão de apagar escondido aqui
                if st.button("🗑️ Excluir Receita", key="del_rec"):
                    doc_id = f"{dados['name']}_{dados['author']}".replace(" ", "_").lower()
                    db.collection("recipes").document(doc_id).delete()
                    st.rerun()
        else:
            st.info("Nenhuma receita salva.")

# ==================================================
# ABA 2: EVENTOS (PRODUÇÃO)
# ==================================================
with aba_evento:
    st.subheader("🎉 Controle de Evento")
    st.caption("Vai vender em feira ou evento? Dê baixa no estoque por aqui.")
    
    if receitas:
        c1, c2, c3 = st.columns([2,1,1])
        r_evt = c1.selectbox("O que foi vendido?", [r['name'] for r in receitas], key="evt_sel")
        q_evt = c2.number_input("Quantidade Vendida", 1, 1000, 1)
        
        if c3.button("Registrar Venda", type="primary"):
            sucesso = registrar_evento(r_evt, q_evt)
            if sucesso:
                st.balloons()
                st.success(f"Venda de {q_evt}x {r_evt} registrada! Estoque atualizado.")
            else:
                st.error("Erro ao registrar.")
    else:
        st.warning("Crie receitas primeiro.")

# ==================================================
# ABA 3: ESTOQUE (CONTROLE PESSOAL)
# ==================================================
with aba_estoque:
    st.subheader("📦 Minha Despensa")
    st.caption("Aqui fica o que sobrou. Você pode ajustar manualmente se usar em casa.")
    
    # Adicionar item avulso
    with st.expander("➕ Compra de Mercado (Avulsa)"):
        ca1, ca2, ca3 = st.columns(3)
        n_avulso = ca1.text_input("Item comprado")
        q_avulso = ca2.number_input("Qtd Total (g/ml/unid)", 0.0)
        
        if st.button("Salvar no Estoque"):
            sid = f"{n_avulso}_generico".replace(" ", "_").lower()
            db.collection("inventory").document(sid).set({
                "nome": n_avulso, "estoque_atual": q_avulso, "marca": "Avulso"
            }, merge=True)
            st.success("Adicionado!")
            st.rerun()
            
    # Tabela
    items = pegar_estoque()
    if items:
        df_est = pd.DataFrame(items)
        # Mostra só colunas úteis
        cols_uteis = [c for c in ["nome", "estoque_atual", "marca"] if c in df_est.columns]
        
        # Editor para correção rápida (uso pessoal)
        editado = st.data_editor(df_est[cols_uteis], key="editor_estoque", num_rows="dynamic")
        
        # Lógica para salvar edições manuais seria complexa aqui, 
        # então deixamos apenas visualização ou adição acima para manter "Casual".

# ==================================================
# ABA 4: HISTÓRICO
# ==================================================
with aba_historico:
    st.subheader("📅 Diário de Vendas & Produção")
    
    logs = db.collection("history").order_by("data", direction=firestore.Query.DESCENDING).stream()
    lista_logs = [l.to_dict() for l in logs]
    
    if lista_logs:
        for l in lista_logs:
            data_str = l['data'].strftime("%d/%m - %H:%M") if l.get('data') else ""
            st.info(f"**{data_str}**: {l.get('qtd',0)}x {l.get('receita','?')} ({l.get('tipo','Produção')})")
    else:
        st.caption("Nada registrado ainda.")
