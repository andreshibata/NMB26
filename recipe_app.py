import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Gestor de Receitas", layout="wide", page_icon="🍳")

# --- 2. CONEXÃO SEGURA ---
@st.cache_resource
def conectar_banco():
    if not firebase_admin._apps:
        try:
            # Tenta local
            cred = credentials.Certificate("firebase_key.json") 
            firebase_admin.initialize_app(cred)
        except:
            # Tenta nuvem
            if "textkey" in st.secrets:
                key_dict = json.loads(st.secrets["textkey"])
                cred = credentials.Certificate(key_dict)
                firebase_admin.initialize_app(cred)
            else:
                st.error("❌ Erro: Chave do banco não encontrada.")
                st.stop()
    return firestore.client()

db = conectar_banco()

# --- 3. FUNÇÕES ---

def pegar_despensa_dict():
    docs = db.collection("ingredients").stream()
    return {doc.to_dict()['name']: doc.to_dict() for doc in docs}

def salvar_nova_receita(nome, autor, ingredientes):
    doc_id = f"{nome.replace(' ', '_').lower()}_{autor.replace(' ', '_').lower()}"
    custo_total = sum(i['custo_final'] for i in ingredientes)
    
    # Salva Receita
    db.collection("recipes").document(doc_id).set({
        "name": nome,
        "author": autor,
        "ingredients": ingredientes,
        "total_cost": custo_total,
        "created_at": firestore.SERVER_TIMESTAMP
    })
    
    # Atualiza Despensa
    for item in ingredientes:
        safe_id = item['nome'].replace(" ", "_").lower()
        db.collection("ingredients").document(safe_id).set({
            "name": item['nome'],
            "price": item['preco_compra'],
            "pkg_amount": item['tam_pacote'],
            "unit": item['unidade'],
            "price_per_unit": item['custo_unitario']
        })

def atualizar_receita_existente(doc_id, nome, autor, ingredientes):
    custo_total = sum(i['custo_final'] for i in ingredientes)
    db.collection("recipes").document(doc_id).set({
        "name": nome,
        "author": autor,
        "ingredients": ingredientes,
        "total_cost": custo_total,
        "updated_at": firestore.SERVER_TIMESTAMP
    }, merge=True)

def apagar_receita(doc_id):
    db.collection("recipes").document(doc_id).delete()

def pegar_todas_receitas_com_id():
    docs = db.collection("recipes").stream()
    lista = []
    for doc in docs:
        d = doc.to_dict()
        d['id'] = doc.id
        lista.append(d)
    return lista

# --- 4. ESTADO DA SESSÃO ---
if 'ingredientes_temp' not in st.session_state:
    st.session_state.ingredientes_temp = []
if 'buffer_edicao' not in st.session_state:
    st.session_state.buffer_edicao = []

# --- 5. APLICATIVO ---

# --- LOGIN ---
with st.sidebar:
    st.title("🔐 Acesso")
    senha_digitada = st.text_input("Senha", type="password")
    senha_correta = st.secrets.get("senha_app", "admin")
    
    if senha_digitada == senha_correta:
        st.success("Conectado")
        acesso = True
    else:
        st.warning("Digite a senha.")
        acesso = False

if not acesso:
    st.stop()

# --- TELA PRINCIPAL ---
st.title("🍳 Gestor Profissional de Receitas")

despensa = pegar_despensa_dict()
nomes_conhecidos = sorted(list(despensa.keys()))

aba_criar, aba_editar, aba_ver = st.tabs(["📝 Criar Nova", "✏️ Editar & Apagar", "📊 Margem & Lucro"])

# =========================================
# ABA 1: CRIAR NOVA
# =========================================
with aba_criar:
    st.caption("Adicione ingredientes. O sistema aprende os preços automaticamente.")
    
    with st.container(border=True):
        c1, c2 = st.columns([1, 1])
        tipo = c1.radio("Modo:", ["Existente", "Novo"], horizontal=True, label_visibility="collapsed", key="tipo_criar")
        
        if tipo == "Existente" and nomes_conhecidos:
            sel = c1.selectbox("Item", nomes_conhecidos, key="sel_criar")
            dados = despensa[sel]
            v_preco, v_tam, v_unid = float(dados['price']), float(dados['pkg_amount']), dados['unit']
            nome_f = sel
        else:
            nome_f = c1.text_input("Nome", key="nome_criar")
            v_preco, v_tam, v_unid = 0.0, 0.0, "g"

        cp, ct, cu, cuse = st.columns(4)
        p = cp.number_input("Preço (R$)", value=v_preco, key="p_criar")
        t = ct.number_input("Tam. Pacote", value=v_tam, key="t_criar")
        u = cu.selectbox("Unid.", ["g", "ml", "unid", "kg", "L"], index=["g", "ml", "unid", "kg", "L"].index(v_unid) if v_unid in ["g", "ml", "unid", "kg", "L"] else 0, key="u_criar")
        qtd = cuse.number_input("Qtd. Usada", key="qtd_criar")

        if st.button("Adicionar", key="btn_add_criar"):
            if nome_f and t > 0:
                custo_u = p / t
                st.session_state.ingredientes_temp.append({
                    "nome": nome_f,
                    "preco_compra": p,
                    "tam_pacote": t,
                    "unidade": u,
                    "qtd_usada": qtd,
                    "custo_unitario": custo_u,
                    "custo_final": custo_u * qtd
                })
                st.rerun()

    if st.session_state.ingredientes_temp:
        st.divider()
        df = pd.DataFrame(st.session_state.ingredientes_temp)
        st.dataframe(df[["nome", "qtd_usada", "unidade", "custo_final"]], use_container_width=True)
        
        with st.form("salvar_nova"):
            c1, c2 = st.columns(2)
            n_rec = c1.text_input("Nome Receita")
            n_aut = c2.text_input("Autor")
            if st.form_submit_button("💾 Salvar"):
                if n_rec and n_aut:
                    salvar_nova_receita(n_rec, n_aut, st.session_state.ingredientes_temp)
                    st.success("Salvo!")
                    st.session_state.ingredientes_temp = []
                    st.rerun()
        
        if st.button("Limpar Lista", key="limpar_criar"):
            st.session_state.ingredientes_temp = []
            st.rerun()

# =========================================
# ABA 2: EDITAR E APAGAR
# =========================================
with aba_editar:
    st.header("Gerenciar Receitas Existentes")
    
    receitas = pegar_todas_receitas_com_id()
    
    if receitas:
        opcoes = [f"{r['name']} ({r['author']})" for r in receitas]
        escolha = st.selectbox("Selecione para Editar/Apagar", opcoes, key="sel_editar")
        
        rec_original = next(r for r in receitas if f"{r['name']} ({r['author']})" == escolha)
        
        # Botão para carregar os dados para a memória de edição
        if st.button("🔄 Carregar Dados", key="btn_load"):
            st.session_state.buffer_edicao = rec_original['ingredients']
            st.session_state.edit_id = rec_original['id']
            st.session_state.edit_nome = rec_original['name']
            st.session_state.edit_autor = rec_original['author']
            st.rerun()

        # Área de Edição (Só aparece se tiver carregado)
        if 'edit_id' in st.session_state and st.session_state.edit_id == rec_original['id']:
            st.divider()
            
            # 1. Editar Metadados
            c_meta1, c_meta2 = st.columns(2)
            novo_nome = c_meta1.text_input("Editar Nome", value=st.session_state.edit_nome)
            novo_autor = c_meta2.text_input("Editar Autor", value=st.session_state.edit_autor)
            
            # 2. Tabela Editável
            st.subheader("Ingredientes")
            st.caption("Dica: Para remover um item, mude a 'Qtd Usada' para 0.")
            
            df_edit = pd.DataFrame(st.session_state.buffer_edicao)
            
            # Editor de dados (permite mudar valores na tabela)
            tabela_editada = st.data_editor(
                df_edit,
                column_config={
                    "qtd_usada": st.column_config.NumberColumn("Qtd Usada", min_value=0.0),
                    "nome": st.column_config.TextColumn("Ingrediente", disabled=True),
                    "custo_final": st.column_config.NumberColumn("Custo", disabled=True)
                },
                hide_index=True,
                use_container_width=True,
                key="editor_tabela"
            )
            
            # 3. Adicionar NOVO item na edição
            with st.expander("➕ Adicionar Item Extra nessa Receita"):
                ce1, ce2, ce3, ce4 = st.columns([2,1,1,1])
                # Usa nomes conhecidos para facilitar
                add_nome = ce1.selectbox("Item", nomes_conhecidos, key="add_edit_sel") if nomes_conhecidos else ce1.text_input("Nome", key="add_edit_txt")
                
                # Pega dados default se existir
                d_def = despensa.get(add_nome, {})
                vp = float(d_def.get('price', 0))
                vt = float(d_def.get('pkg_amount', 0))
                vu = d_def.get('unit', 'g')
                
                add_qtd = ce2.number_input("Qtd", key="add_edit_qtd")
                # Mostra preço só pra confirmar
                ce3.caption(f"Ref: R$ {vp:.2f} / {vt:.0f}{vu}")
                
                if ce4.button("Incluir", key="btn_incluir_edit"):
                    if vt > 0:
                        cu = vp / vt
                        st.session_state.buffer_edicao.append({
                            "nome": add_nome,
                            "preco_compra": vp,
                            "tam_pacote": vt,
                            "unidade": vu,
                            "qtd_usada": add_qtd,
                            "custo_unitario": cu,
                            "custo_final": cu * add_qtd
                        })
                        st.rerun()

            st.divider()
            
            # 4. Botões de Ação (Salvar ou Apagar)
            col_save, col_del = st.columns([3, 1])
            
            if col_save.button("💾 Salvar Alterações", type="primary", key="btn_save_edit"):
                # Recalcula custos baseado na tabela editada
                ingredientes_finais = []
                for index, row in tabela_editada.iterrows():
                    if row['qtd_usada'] > 0: # Remove itens zerados
                        custo_novo = row['custo_unitario'] * row['qtd_usada']
                        ingredientes_finais.append({
                            "nome": row['nome'],
                            "preco_compra": row['preco_compra'],
                            "tam_pacote": row['tam_pacote'],
                            "unidade": row['unidade'],
                            "qtd_usada": row['qtd_usada'],
                            "custo_unitario": row['custo_unitario'],
                            "custo_final": custo_novo
                        })
                
                atualizar_receita_existente(st.session_state.edit_id, novo_nome, novo_autor, ingredientes_finais)
                st.success("Receita Atualizada!")
                
            if col_del.button("🗑️ APAGAR RECEITA", type="secondary", key="btn_del"):
                apagar_receita(st.session_state.edit_id)
                st.error(f"Receita '{st.session_state.edit_nome}' foi apagada.")
                # Limpa a memória
                del st.session_state['edit_id']
                st.rerun()

# =========================================
# ABA 3: LUCRO
# =========================================
with aba_ver:
    st.header("Análise Financeira")
    lista_r = pegar_todas_receitas_com_id()
    
    if lista_r:
        sel_v = st.selectbox("Receita", [r['name'] for r in lista_r], key="sel_ver")
        dados = next(r for r in lista_r if r['name'] == sel_v)
        
        st.dataframe(pd.DataFrame(dados['ingredients'])[["nome", "qtd_usada", "custo_final"]], use_container_width=True)
        
        custo = dados['total_cost']
        c1, c2, c3 = st.columns(3)
        c1.metric("Custo Total", f"R$ {custo:.2f}")
        
        pv = c2.number_input("Preço Venda", value=custo*3, key="pv_ver")
        if pv > 0:
            lucro = pv - custo
            margem = (lucro / pv) * 100
            c3.metric("Margem", f"{margem:.1f}%", delta=f"R$ {lucro:.2f}")
