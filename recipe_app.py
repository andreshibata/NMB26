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
                st.error("🔌 Erro de conexão com a base de dados.")
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

def salvar_receita(nome, autor, ingredientes, rendimento):
    doc_id = f"{nome}_{autor}".replace(" ", "_").lower()
    custo = sum(i['custo_final'] for i in ingredientes)
    db.collection("recipes").document(doc_id).set({
        "name": nome, "author": autor, "rendimento": rendimento,
        "ingredients": ingredientes, "total_cost": custo,
        "updated_at": firestore.SERVER_TIMESTAMP
    }, merge=True)

def apagar_receita(doc_id):
    db.collection("recipes").document(doc_id).delete()

# --- FUNÇÕES DE PLANEAMENTO ---
def pegar_planeamentos():
    docs = db.collection("productions").stream()
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

def salvar_planeamento(nome, fila):
    doc_id = nome.replace(" ", "_").lower()
    db.collection("productions").document(doc_id).set({
        "nome": nome, "fila": fila,
        "updated_at": firestore.SERVER_TIMESTAMP
    }, merge=True)

def apagar_planeamento(doc_id):
    db.collection("productions").document(doc_id).delete()

# --- 4. FUNÇÃO VISUAL ---
def cartao_financeiro(titulo, valor, cor_borda, icone, subtitulo=""):
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
    st.caption("Administração")
    if st.text_input("Palavra-passe", type="password") != st.secrets.get("senha_app", "admin"):
        st.warning("🔒 Digite a palavra-passe para aceder."); st.stop()

# ESTADO DA SESSÃO
if 'fila_producao' not in st.session_state: st.session_state.fila_producao = []
if 'nome_plano_atual' not in st.session_state: st.session_state.nome_plano_atual = ""
if 'df_ingredientes' not in st.session_state:
    st.session_state.df_ingredientes = pd.DataFrame(columns=["Tipo", "Nome", "Preco_Pacote", "Tam_Pacote", "Medida", "Qtd_Usada"])
if 'rec_nome_edicao' not in st.session_state: st.session_state.rec_nome_edicao = ""
if 'rec_autor_edicao' not in st.session_state: st.session_state.rec_autor_edicao = "Chef"
if 'rec_rendimento_edicao' not in st.session_state: st.session_state.rec_rendimento_edicao = 1.0

receitas_salvas = pegar_receitas()
dict_receitas = {r['name']: r for r in receitas_salvas}

# ABAS PRINCIPAIS
aba_criar, aba_listar, aba_calculadora = st.tabs([
    "📝 Criar / Editar Receita", 
    "📚 As Minhas Receitas", 
    "🛒 Planeador de Produção"
])

# ==================================================
# ABA 1: CRIAR / EDITAR RECEITA
# ==================================================
with aba_criar:
    with st.expander("✏️ Carregar uma Receita Existente para Editar"):
        opcoes_edicao = ["-- Selecione para editar --"] + list(dict_receitas.keys())
        rec_selecionada = st.selectbox("Receitas Guardadas:", opcoes_edicao)
        if st.button("Carregar Dados"):
            if rec_selecionada != "-- Selecione para editar --":
                rec_dados = dict_receitas[rec_selecionada]
                st.session_state.rec_nome_edicao = rec_dados['name']
                st.session_state.rec_autor_edicao = rec_dados.get('author', 'Chef')
                st.session_state.rec_rendimento_edicao = rec_dados.get('rendimento', 1.0) 
                
                df_temp = pd.DataFrame(rec_dados['ingredients'])
                novo_df = pd.DataFrame()
                novo_df['Tipo'] = df_temp['tipo'] if 'tipo' in df_temp.columns else 'Ingrediente'
                novo_df['Nome'] = df_temp['nome']
                novo_df['Preco_Pacote'] = df_temp['preco_compra']
                novo_df['Tam_Pacote'] = df_temp['tam_pacote']
                novo_df['Medida'] = df_temp['unidade']
                novo_df['Qtd_Usada'] = df_temp['qtd_usada']
                st.session_state.df_ingredientes = novo_df
                st.rerun()

    st.divider()
    
    col_info1, col_info2, col_info3 = st.columns([2, 1, 1])
    with col_info1: nome_receita = st.text_input("Nome da Receita", value=st.session_state.rec_nome_edicao)
    with col_info2: autor_receita = st.text_input("Criador/Chef", value=st.session_state.rec_autor_edicao)
    with col_info3: rendimento_receita = st.number_input("Rende quantas PORÇÕES?", min_value=0.1, value=float(st.session_state.rec_rendimento_edicao), step=1.0)

    st.markdown("### 🛒 Ingredientes e Sub-receitas")
    
    with st.popover("➕ Adicionar uma Sub-Receita"):
        if receitas_salvas:
            sel_sub = st.selectbox("Escolher Receita Base", list(dict_receitas.keys()))
            qtd_sub = st.number_input("Quantas PORÇÕES vai usar?", min_value=0.01, value=1.0)
            if st.button("Inserir Sub-Receita na Tabela"):
                rec_sub_dados = dict_receitas[sel_sub]
                rendimento_sub = rec_sub_dados.get('rendimento', 1.0)
                nova_linha = pd.DataFrame([{
                    "Tipo": "Sub-receita", "Nome": rec_sub_dados['name'],
                    "Preco_Pacote": rec_sub_dados['total_cost'], "Tam_Pacote": rendimento_sub, 
                    "Medida": "porções", "Qtd_Usada": qtd_sub 
                }])
                st.session_state.df_ingredientes = pd.concat([st.session_state.df_ingredientes, nova_linha], ignore_index=True)
                st.rerun()
        else:
            st.warning("Sem receitas guardadas.")
    
    edited_df = st.data_editor(
        st.session_state.df_ingredientes, num_rows="dynamic",
        column_config={
            "Tipo": st.column_config.SelectboxColumn("Tipo", options=["Ingrediente", "Sub-receita"], default="Ingrediente"),
            "Nome": st.column_config.TextColumn("Nome do Item", required=True),
            "Preco_Pacote": st.column_config.NumberColumn("Preço Pacote (R$)", min_value=0.0, format="%.2f"), 
            "Tam_Pacote": st.column_config.NumberColumn("Tamanho Pacote", min_value=0.0001),
            "Medida": st.column_config.SelectboxColumn("Medida", options=["g", "ml", "unid", "kg", "L", "receita", "porções"]),
            "Qtd_Usada": st.column_config.NumberColumn("Qtd Usada na Receita", min_value=0.0001)
        }, use_container_width=True, hide_index=True
    )

    custo_total_estimado = 0
    ingredientes_processados = []
    
    for _, row in edited_df.dropna(how='any').iterrows():
        if row['Tam_Pacote'] > 0:
            nome_limpo = str(row['Nome']).strip().title()
            custo_linha = (row['Preco_Pacote'] / row['Tam_Pacote']) * row['Qtd_Usada']
            custo_total_estimado += custo_linha
            ingredientes_processados.append({
                "tipo": row['Tipo'], "nome": nome_limpo if row['Tipo'] == 'Ingrediente' else row['Nome'], 
                "preco_compra": row['Preco_Pacote'], "tam_pacote": row['Tam_Pacote'],
                "unidade": row['Medida'], "qtd_usada": row['Qtd_Usada'], "custo_final": custo_linha
            })

    if custo_total_estimado >= 0:
        st.info(f"💰 Custo Fornada: **R$ {custo_total_estimado:.2f}** | 🍽️ 1 Porção: **R$ {(custo_total_estimado / rendimento_receita if rendimento_receita > 0 else 0):.2f}**")

    c_save, c_clear = st.columns([1, 4])
    if c_save.button("💾 Guardar Receita", type="primary"):
        if nome_receita and ingredientes_processados:
            salvar_receita(nome_receita, autor_receita, ingredientes_processados, rendimento_receita)
            st.success("Guardada com sucesso!"); st.rerun()
            
    if c_clear.button("🗑️ Limpar Formulário"):
        st.session_state.df_ingredientes = pd.DataFrame(columns=["Tipo", "Nome", "Preco_Pacote", "Tam_Pacote", "Medida", "Qtd_Usada"])
        st.rerun()

# ==================================================
# ABA 2: AS MINHAS RECEITAS
# ==================================================
with aba_listar:
    st.subheader("📚 Base de Dados de Receitas")
    if receitas_salvas:
        for rec in receitas_salvas:
            rend_salvo = rec.get('rendimento', 1.0)
            custo_por_porcao = rec['total_cost'] / rend_salvo if rend_salvo > 0 else 0
            with st.expander(f"🍽️ {rec['name']} - Rende {rend_salvo} porções | Porção: R$ {custo_por_porcao:.2f} | Total: R$ {rec['total_cost']:.2f}"):
                df_ing = pd.DataFrame(rec['ingredients'])
                if 'tipo' not in df_ing.columns: df_ing['tipo'] = 'Ingrediente'
                st.dataframe(df_ing[["tipo", "nome", "qtd_usada", "unidade", "custo_final"]], use_container_width=True, hide_index=True)
                if st.button("🗑️ Apagar esta receita", key=f"del_{rec['id']}"):
                    apagar_receita(rec['id']); st.rerun()
    else: st.info("Ainda não tem receitas guardadas.")

# ==================================================
# ABA 3: PLANEADOR DE PRODUÇÃO E VENDAS
# ==================================================
with aba_calculadora:
    st.subheader("🛒 Carrinho de Produção")
    
    with st.expander("📂 Carregar / Gerir Planeamentos de Produção Salvos"):
        planos_salvos = pegar_planeamentos()
        if planos_salvos:
            p_sel = st.selectbox("Escolha um planeamento guardado", ["-- Selecione --"] + [p['nome'] for p in planos_salvos])
            colA, colB = st.columns(2)
            if colA.button("📥 Carregar na Tabela"):
                if p_sel != "-- Selecione --":
                    plano_escolhido = next(p for p in planos_salvos if p['nome'] == p_sel)
                    st.session_state.fila_producao = plano_escolhido['fila']
                    st.session_state.nome_plano_atual = plano_escolhido['nome']
                    st.rerun()
            if colB.button("🗑️ Apagar do Banco"):
                if p_sel != "-- Selecione --":
                    plano_escolhido = next(p for p in planos_salvos if p['nome'] == p_sel)
                    apagar_planeamento(plano_escolhido['id'])
                    st.success("Apagado!"); st.rerun()
        else:
            st.info("Nenhum planeamento salvo ainda. Guarde um no fim da página!")

    col_markup, col_vazia2 = st.columns([1, 2])
    with col_markup:
        markup_padrao = st.number_input("📈 Markup Inicial Sugerido", min_value=1.0, value=3.0, step=0.1)
    
    st.divider()

    if receitas_salvas:
        with st.container(border=True):
            c_sel, c_qtd, c_btn = st.columns([2, 1, 1])
            r_escolhida = c_sel.selectbox("Escolha a Receita", list(dict_receitas.keys()))
            dados_rec = dict_receitas.get(r_escolhida)
            multiplicador = c_qtd.number_input("Fornadas (Múltiplos da Receita Inteira)", min_value=1.0, value=1.0, step=1.0)
            
            if c_btn.button("➕ Adicionar à Fila"):
                st.session_state.fila_producao.append({
                    "receita": dados_rec, "qtd": multiplicador, "preco_venda_porcao": None 
                })
                st.rerun()

        if st.session_state.fila_producao:
            # --- MOTOR DE NORMALIZAÇÃO DE MEDIDAS (RESOLVE O BUG DO KG VS G) ---
            def extrair_ingredientes_base(receita, mult_atual):
                ingredientes_finais = []
                for ing in receita['ingredients']:
                    if ing.get('tipo', 'Ingrediente') == 'Sub-receita':
                        sub_rec_dados = dict_receitas.get(ing['nome'])
                        if sub_rec_dados:
                            mult_sub = (ing['qtd_usada'] / ing['tam_pacote']) * mult_atual
                            ingredientes_finais.extend(extrair_ingredientes_base(sub_rec_dados, mult_sub))
                    else:
                        ing_copy = ing.copy()
                        
                        # --- INÍCIO DA NORMALIZAÇÃO ---
                        medida = ing_copy.get('unidade', 'unid')
                        qtd = ing_copy.get('qtd_usada', 0)
                        tam = ing_copy.get('tam_pacote', 1)
                        
                        if medida == 'kg':
                            qtd = qtd * 1000
                            tam = tam * 1000
                            medida = 'g'
                        elif medida == 'L':
                            qtd = qtd * 1000
                            tam = tam * 1000
                            medida = 'ml'
                            
                        ing_copy['qtd_usada'] = qtd * mult_atual
                        ing_copy['tam_pacote'] = tam
                        ing_copy['unidade'] = medida
                        # Custo recalcullado para garantir a precisão
                        ing_copy['custo_final'] = (ing_copy['preco_compra'] / tam) * ing_copy['qtd_usada']
                        # --- FIM DA NORMALIZAÇÃO ---
                        
                        ingredientes_finais.append(ing_copy)
                return ingredientes_finais

            st.markdown("### 🔍 Precificação e Produção (Editável)")
            
            tabela_por_receita = []
            for index, item in enumerate(st.session_state.fila_producao):
                ing_puros_item = extrair_ingredientes_base(item['receita'], item['qtd'])
                custo_total_fornada_produzida = sum(i['custo_final'] for i in ing_puros_item)
                
                rendimento_base = item['receita'].get('rendimento', 1.0)
                porcoes_totais_produzidas = item['qtd'] * rendimento_base
                custo_de_uma_porcao = custo_total_fornada_produzida / porcoes_totais_produzidas if porcoes_totais_produzidas > 0 else 0
                
                if item.get('preco_venda_porcao') is None:
                    item['preco_venda_porcao'] = custo_de_uma_porcao * markup_padrao
                
                venda_de_uma_porcao = item['preco_venda_porcao']
                faturamento_total_desta_receita = venda_de_uma_porcao * porcoes_totais_produzidas
                markup_real = venda_de_uma_porcao / custo_de_uma_porcao if custo_de_uma_porcao > 0 else 0
                lucro_total_projetado = faturamento_total_desta_receita - custo_total_fornada_produzida
                
                tabela_por_receita.append({
                    "Produto": item['receita']['name'],
                    "✏️ Fornadas": float(item['qtd']),
                    "Rende (Porções)": porcoes_totais_produzidas,
                    "Custo (1 Porção)": float(custo_de_uma_porcao),
                    "✏️ Preço Venda (1 Porção)": float(venda_de_uma_porcao),
                    "Markup Atual": f"{markup_real:.2f}x",
                    "Lucro Projetado (Total)": float(lucro_total_projetado)
                })
            
            df_precificacao = pd.DataFrame(tabela_por_receita)
            
            edited_df_analise = st.data_editor(
                df_precificacao,
                column_config={
                    "Produto": st.column_config.TextColumn("Produto", disabled=True),
                    "✏️ Fornadas": st.column_config.NumberColumn("✏️ Fornadas", min_value=0.0, step=1.0),
                    "Rende (Porções)": st.column_config.NumberColumn("Rende (Porções)", disabled=True),
                    "Custo (1 Porção)": st.column_config.NumberColumn("Custo (1 Porção)", format="R$ %.2f", disabled=True),
                    "✏️ Preço Venda (1 Porção)": st.column_config.NumberColumn("✏️ Preço Venda (1 Porção)", format="R$ %.2f", min_value=0.0),
                    "Markup Atual": st.column_config.TextColumn("Markup Atual", disabled=True),
                    "Lucro Projetado (Total)": st.column_config.NumberColumn("Lucro Projetado (Total)", format="R$ %.2f", disabled=True)
                }, use_container_width=True, hide_index=True
            )
            
            mudou = False
            for i, row in edited_df_analise.iterrows():
                novo_preco = row['✏️ Preço Venda (1 Porção)']
                nova_qtd = row['✏️ Fornadas']
                
                if st.session_state.fila_producao[i].get('preco_venda_porcao') != novo_preco or st.session_state.fila_producao[i]['qtd'] != nova_qtd:
                    st.session_state.fila_producao[i]['preco_venda_porcao'] = novo_preco
                    st.session_state.fila_producao[i]['qtd'] = nova_qtd
                    mudou = True
            
            if mudou:
                st.session_state.fila_producao = [item for item in st.session_state.fila_producao if item['qtd'] > 0]
                st.rerun()

            c_down_prec, c_clear = st.columns([1, 1])
            csv_precificacao = df_precificacao.to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig')
            c_down_prec.download_button("⬇️ Exportar Precificação (CSV)", data=csv_precificacao, file_name="precificacao.csv", mime="text/csv", use_container_width=True)
            if c_clear.button("🗑️ Limpar Carrinho Inteiro", use_container_width=True):
                st.session_state.fila_producao = []; st.rerun()

            st.divider()

            # --- CONSOLIDAÇÃO DA LISTA DE COMPRAS ---
            ingredientes_consolidados = {}
            custo_proporcional_total = 0
            
            for item in st.session_state.fila_producao:
                lista_ingredientes_puros = extrair_ingredientes_base(item['receita'], item['qtd'])
                for ing in lista_ingredientes_puros:
                    nome = ing['nome']
                    if nome not in ingredientes_consolidados:
                        ingredientes_consolidados[nome] = {"qtd_total": 0, "tam_pacote": ing['tam_pacote'], "preco_compra": ing['preco_compra'], "unidade": ing['unidade'], "custo_prop_acumulado": 0}
                    ingredientes_consolidados[nome]["qtd_total"] += ing['qtd_usada']
                    ingredientes_consolidados[nome]["custo_prop_acumulado"] += ing['custo_final']
                    custo_proporcional_total += ing['custo_final']

            desembolso_mercado_total = 0
            lista_compras = []
            
            for nome, dados in ingredientes_consolidados.items():
                # O pacote e a quantidade total já estão na mesma unidade base (ex: tudo em gramas) graças à normalização
                pacotes_necessarios = math.ceil(dados["qtd_total"] / dados["tam_pacote"])
                custo_mercado_ing = pacotes_necessarios * dados["preco_compra"]
                desembolso_mercado_total += custo_mercado_ing
                
                # Para exibição, mostra a unidade que ficou (g ou ml)
                lista_compras.append({
                    "Ingrediente": nome,
                    "Necessidade Real": f"{dados['qtd_total']:.1f} {dados['unidade']}",
                    "Comprar (Pacotes Fechados)": f"{pacotes_necessarios}x ({dados['tam_pacote']}{dados['unidade']})",
                    "Desembolso Caixa": f"R$ {custo_mercado_ing:.2f}"
                })

            st.markdown("### 📊 Orçamento Total Consolidado")
            col_res1, col_res2, col_res3 = st.columns(3)
            with col_res1: cartao_financeiro("Custo Proporcional", custo_proporcional_total, "#FF9800", "⚖️", "Custo das gramas utilizadas.")
            with col_res2: cartao_financeiro("Desembolso de Caixa", desembolso_mercado_total, "#F44336", "🛒", "Valor total no mercado.")
            with col_res3:
                faturamento_projetado = sum((item['preco_venda_porcao'] * (item['qtd'] * item['receita'].get('rendimento', 1.0))) for item in st.session_state.fila_producao)
                cartao_financeiro("Faturamento Projetado", faturamento_projetado, "#4CAF50", "🤑", "Soma de todas as vendas.")
            
            st.markdown("### 📝 Lista de Compras Pura (Mercado)")
            df_compras = pd.DataFrame(lista_compras)
            st.dataframe(df_compras, use_container_width=True, hide_index=True)
            
            csv_compras = df_compras.to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig')
            st.download_button("⬇️ Baixar Lista de Compras (CSV)", data=csv_compras, file_name="lista_compras.csv", mime="text/csv")

            st.divider()
            
            st.markdown("### 💾 Guardar este Planeamento")
            c_nome_plano, c_salvar_plano = st.columns([3, 1])
            nome_novo_plano = c_nome_plano.text_input("Nome (ex: Encomenda Sexta-feira)", value=st.session_state.nome_plano_atual)
            if c_salvar_plano.button("Guardar Planeamento", use_container_width=True):
                if nome_novo_plano:
                    salvar_planeamento(nome_novo_plano, st.session_state.fila_producao)
                    st.session_state.nome_plano_atual = nome_novo_plano
                    st.success("Planeamento guardado no banco de dados!")
                else:
                    st.error("Dê um nome ao planeamento antes de guardar.")

    else:
        st.warning("Crie e guarde uma receita na primeira aba para utilizar o planeador.")
