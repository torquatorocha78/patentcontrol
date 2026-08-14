# app.py
import streamlit as st
import pandas as pd
from datetime import datetime
import database as db
import utils
import ai_analyzer
import report_generator

st.set_page_config(
    page_title="Gestão de Propriedade Intelectual IFSC",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

db.init_database()


def data_para_input(valor):
    if valor is None or pd.isna(valor) or valor == "":
        return None
    try:
        return pd.to_datetime(valor).date()
    except Exception:
        return None


def texto(valor):
    if valor is None or pd.isna(valor):
        return ""
    return str(valor)

st.markdown("""
<style>
    .status-verde { color: #00CC00; font-weight: bold; }
    .status-amarelo { color: #FFCC00; font-weight: bold; }
    .status-vermelho { color: #FF0000; font-weight: bold; }
    .status-pago { color: #0099FF; font-weight: bold; }
    .title-ifsc { text-align: center; color: #003366; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="title-ifsc">🏛️ Gestão de Ativos de PI do IFSC</h1>', unsafe_allow_html=True)
st.markdown('<p style="text-align: center; color: #666;">Patentes, Softwares e Desenhos Industriais - IFSC</p>', unsafe_allow_html=True)
st.divider()

st.sidebar.title("⚙️ Navegação")
pagina = st.sidebar.radio("Selecione uma página:", 
    ["📊 Dashboard", "➕ Adicionar Ativo", "📁 Meus Ativos", "📤 Importar Excel", "🤖 Análise IA", "📄 Gerar Relatórios"])

if pagina == "📊 Dashboard":
    st.title("📊 Dashboard de Propriedade Intelectual")

    df_patentes = db.obter_patentes()

    if len(df_patentes) == 0:
        st.info("📭 Nenhum ativo cadastrado ainda. Adicione um ativo para começar!")
    else:
        total_ativos = len(df_patentes)

        # Divisão por Tipo
        total_p = len(df_patentes[df_patentes['tipo'] == 'Patente'])
        total_s = len(df_patentes[df_patentes['tipo'] == 'Software'])
        total_d = len(df_patentes[df_patentes['tipo'] == 'Desenho Industrial'])

        hoje = datetime.now().date()

        def data_anuidade(valor):
            try:
                return pd.to_datetime(valor).date()
            except Exception:
                return None

        def dados_prazo_ordinario(anu):
            if anu['status'] == 'nao_pagar' or anu['data_pagamento']:
                return None

            inicio_ord = data_anuidade(anu['data_inicio_ordinario'])
            fim_ord = data_anuidade(anu['data_fim_ordinario'])
            if not inicio_ord or not fim_ord or not (inicio_ord <= hoje <= fim_ord):
                return None

            dias_restantes = (fim_ord - hoje).days
            status = 'amarelo' if dias_restantes <= 30 else 'verde'
            return status, dias_restantes

        dados_dashboard = []

        for _, patente in df_patentes.iterrows():
            anuidades = db.obter_anuidades(patente['id'])
            for _, anu in  anuidades.iterrows():
                prazo = dados_prazo_ordinario(anu)
                if not prazo:
                    continue

                status, dias_restantes = prazo
                emoji = utils.criar_emoji_status(status)

                # Nome dinâmico para a taxa
                tipo_ativo = patente.get('tipo', 'Patente')
                if tipo_ativo == 'Software':
                    nome_taxa = "Taxa Registro Único"
                elif tipo_ativo == 'Desenho Industrial':
                    nome_taxa = f"{anu['numero_anuidade']}º Quinquênio"
                else:
                    nome_taxa = f"Anuidade {anu['numero_anuidade']}"

                dados_dashboard.append({
                    "ID": patente['id'],
                    "Tipo": tipo_ativo,
                    "Identificador": patente['numero_patente'],
                    "Título": patente.get('titulo') or "-",
                    "Prazo": nome_taxa,
                    "Fim Prazo Ordinário": utils.formatar_data(anu['data_fim_ordinario']),
                    "Dias p/ Vencer": dias_restantes,
                    "Status": f"{emoji} {status.upper()}",
                    "Gestor": patente.get('gestor', 'N/A')
                })

        alertas_verde = sum(1 for item in dados_dashboard if '✅' in item["Status"])
        alertas_amarelo = sum(1 for item in dados_dashboard if '⚠️' in item["Status"])

        # Métricas em colunas
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("📦 Ativos Registrados", total_ativos)
        with col2:
            st.metric("📜 Patentes", total_p)
        with col3:
            st.metric("💻 Softwares", total_s)
        with col4:
            st.metric("🎨 Desenhos Industriais", total_d)

        st.divider()
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📅 Taxas em Prazo Ordinário", len(dados_dashboard))
        with col2:
            st.metric("✅ Status Normal", alertas_verde, delta="Normal", delta_color="normal")
        with col3:
            st.metric("⚠️ Requer Atenção", alertas_amarelo, delta="Urgente", delta_color="inverse")

        st.divider()
        st.subheader("Prazos / Taxas Ativas em Prazo Ordinário")

        if len(dados_dashboard) == 0:
            st.info("Nenhuma taxa ou anuidade está em prazo de pagamento ordinário hoje.")
        else:
            df_dashboard = pd.DataFrame(dados_dashboard)
            df_dashboard = df_dashboard.sort_values("Dias p/ Vencer")
            st.dataframe(df_dashboard, use_container_width=True, hide_index=True)

elif pagina == "➕ Adicionar Ativo":
    st.title("➕ Cadastrar Novo Ativo de PI")

    tipo_ativo = st.selectbox(
        "Tipo de Ativo de PI",
        ["Patente", "Software", "Desenho Industrial"],
        help="Escolha o tipo correto para aplicar regras tributárias e fiscais adequadas."
    )

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        numero_patente = st.text_input(
            "Identificador / Número do Registro",
            placeholder="Ex: BR1020220000001",
            help="Registro oficial emitido pelo INPI"
        )

        titulo = st.text_input(
            "Título",
            placeholder="Título do Ativo"
        )

        data_deposito = st.date_input(
            "Data do Depósito (Início)",
            help="Data em que o ativo foi depositado/registrado"
        )

        gestor = st.text_input(
            "Gestor (opcional)",
            placeholder="Ex: IFSC"
        )

        # Campo exclusivo de Software
        if tipo_ativo == "Software":
            linguagem = st.text_input(
                "Linguagem de Programação",
                placeholder="Ex: Python, Javascript, C++"
            )
        else:
            linguagem = None

    with col2:
        data_concessao = st.date_input(
            "Data de Concessão (opcional)",
            value=None,
        )

        titular = st.text_input(
            "Titular/Proprietário (opcional)",
            placeholder="Ex: IFSC"
        )

        inventores = st.text_area(
            "Inventores / Autores (opcional)",
            placeholder="Nomes separados por '/'",
            height=90
        )

        status_patente = st.selectbox(
            "Status do Pedido",
            ["Ativo", "Concedida", "Tramitando", "Indeferido", "Arquivado", "Desistência"]
        )

        campus = st.text_input(
            "Campus (opcional)",
            placeholder="Ex: Campus Joinville"
        )

    descricao = st.text_area(
        "Resumo / Descrição (opcional)",
        placeholder="Descrição do ativo",
        height=100
    )

    atributos = st.text_area(
        "Atributos Adicionais (opcional)",
        height=80
    )

    st.divider()

    # Informativos de regra
    if tipo_ativo == "Software":
        st.info("💡 **Regra Aplicada**: Softwares necessitam de apenas **1 Taxa Única de Registro** válida por até 3 meses após a inserção. Não há anuidades.")
    elif tipo_ativo == "Desenho Industrial":
        st.info("💡 **Regra Aplicada**: Desenhos Industriais são taxados em **Quinquênios (a cada 5 anos)** contados a partir do depósito.")
    else:
        st.info("💡 **Regra Aplicada**: Patentes seguem o fluxo convencional de **20 anuidades** consecutivas.")

    if st.button("✅ Salvar Ativo de PI", use_container_width=True, type="primary"):
        if not numero_patente or not data_deposito:
            st.error("❌ Identificador de Registro e Data de Depósito são campos obrigatórios.")
        else:
            data_dep_str = data_deposito.strftime("%Y-%m-%d")
            data_conc_str = data_concessao.strftime("%Y-%m-%d") if data_concessao else None

            sucesso, mensagem = db.adicionar_patente(
                numero_patente,
                data_dep_str,
                data_conc_str,
                descricao,
                titular,
                gestor,
                status_patente,
                titulo,
                inventores,
                campus,
                atributos,
                tipo_ativo,
                linguagem
            )

            if sucesso:
                st.success("🎉 Ativo de PI registrado com sucesso!")
                st.balloons()
            else:
                st.error(f"❌ Erro ao salvar: {mensagem}")

elif pagina == "📁 Meus Ativos":
    st.title("📁 Gerenciador de Ativos Cadastrados")

    df_patentes = db.obter_patentes()

    if len(df_patentes) == 0:
        st.info("📭 Nenhum ativo encontrado.")
    else:
        # Filtros de Busca
        col_f1, col_f2 = st.columns([3, 1])
        with col_f1:
            busca = st.text_input("Filtrar por nome, número, campus ou inventor:")
        with col_f2:
            filtro_tipo = st.selectbox("Filtrar por Tipo", ["Todos", "Patente", "Software", "Desenho Industrial"])

        df_filtrado = df_patentes.copy()

        if filtro_tipo != "Todos":
            df_filtrado = df_filtrado[df_filtrado['tipo'] == filtro_tipo]

        if busca:
            termo = busca.lower()
            mascara = (
                df_filtrado['numero_patente'].fillna("").str.lower().str.contains(termo) |
                df_filtrado['titulo'].fillna("").str.lower().str.contains(termo) |
                df_filtrado['inventores'].fillna("").str.lower().str.contains(termo) |
                df_filtrado['campus'].fillna("").str.lower().str.contains(termo)
            )
            df_filtrado = df_filtrado[mascara]

        if len(df_filtrado) == 0:
            st.warning("Nenhum ativo corresponde aos critérios de pesquisa.")
        else:
            opcoes = {
                f"[{row.get('tipo', 'Patente')}] {row['numero_patente']} - {row.get('titulo') or 'Sem título'}": row['numero_patente']
                for _, row in df_filtrado.iterrows()
            }
            ativo_label = st.selectbox("Selecione para detalhar ou editar:", list(opcoes.keys()))
            ativo_selecionado = opcoes[ativo_label]

            ativo_dados = df_patentes[df_patentes['numero_patente'] == ativo_selecionado].iloc[0]
            ativo_id = ativo_dados['id']
            tipo_ativo = ativo_dados.get('tipo', 'Patente')

            # Painel Visual de Detalhes
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📋 Tipo de Ativo", tipo_ativo)
            with col2:
                st.metric("📅 Data de Depósito", utils.formatar_data(ativo_dados['data_deposito']))
            with col3:
                st.metric("🎓 Concessão", utils.formatar_data(ativo_dados['data_concessao']) if ativo_dados['data_concessao'] else "Pendente")
            with col4:
                st.metric("📊 Situação", ativo_dados.get('status', 'Ativo'))

            if tipo_ativo == "Software" and ativo_dados.get("linguagem"):
                st.info(f"💻 **Linguagem de Programação**: {ativo_dados['linguagem']}")

            # Expander de Edição
            with st.expander("✏️ Editar dados deste Ativo"):
                with st.form(f"form_editar_{ativo_id}"):
                    col_ed1, col_ed2 = st.columns(2)
                    with col_ed1:
                        edit_numero = st.text_input("Número do Registro", value=texto(ativo_dados.get('numero_patente')))
                        edit_titulo = st.text_input("Título", value=texto(ativo_dados.get('titulo')))
                        edit_data_dep = st.date_input("Data de Depósito", value=data_para_input(ativo_dados.get('data_deposito')))
                        edit_data_conc = st.date_input("Data de Concessão", value=data_para_input(ativo_dados.get('data_concessao')))
                        edit_tipo = st.selectbox("Tipo de Ativo", ["Patente", "Software", "Desenho Industrial"], index=["Patente", "Software", "Desenho Industrial"].index(tipo_ativo))
                        if edit_tipo == "Software":
                            edit_linguagem = st.text_input("Linguagem", value=texto(ativo_dados.get('linguagem')))
                        else:
                            edit_linguagem = None
                    with col_ed2:
                        edit_gestor = st.text_input("Gestor", value=texto(ativo_dados.get('gestor')))
                        edit_campus = st.text_input("Campus", value=texto(ativo_dados.get('campus')))
                        edit_titular = st.text_area("Titular", value=texto(ativo_dados.get('titular')), height=90)
                        edit_inventores = st.text_area("Inventores", value=texto(ativo_dados.get('inventores')), height=90)
                        edit_status = st.text_input("Status", value=texto(ativo_dados.get('status')))

                    edit_descricao = st.text_area("Resumo / Descrição", value=texto(ativo_dados.get('descricao')), height=100)
                    edit_atributos = st.text_area("Atributos", value=texto(ativo_dados.get('atributos')), height=80)

                    if st.form_submit_button("💾 Salvar Alterações"):
                        ok, msg = db.atualizar_patente(
                            ativo_id, edit_numero,
                            edit_data_dep.strftime("%Y-%m-%d") if edit_data_dep else None,
                            edit_data_conc.strftime("%Y-%m-%d") if edit_data_conc else None,
                            edit_descricao, edit_titular, edit_gestor, edit_status,
                            edit_titulo, edit_inventores, edit_campus, edit_atributos,
                            edit_tipo, edit_linguagem
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

            st.divider()
            st.subheader("💰 Cronograma de Taxas e Pagamentos")

            anuidades = db.obter_anuidades(ativo_id)

            if anuidades.empty:
                st.warning("Nenhum registro de taxa gerado.")
            else:
                dados_tabela = []
                for _, anu in anuidades.iterrows():
                    # Definindo nomenclaturas fiscais baseadas no tipo de ativo
                    if tipo_ativo == "Software":
                        nome_taxa = "Taxa Única de Registro"
                    elif tipo_ativo == "Desenho Industrial":
                        nome_taxa = f"Quinquênio {anu['numero_anuidade']} (Anos {5*(anu['numero_anuidade']-1)} a {5*anu['numero_anuidade']})"
                    else:
                        nome_taxa = f"Anuidade Ordinária {anu['numero_anuidade']}"

                    if anu['status'] == 'nao_pagar':
                        status_disp = '⛔ ISENTO/NÃO PAGAR'
                        dias_restantes = '-'
                    else:
                        status_calc = utils.calcular_status_anuidade(
                            anu['data_inicio_ordinario'],
                            anu['data_fim_ordinario'],
                            anu['data_inicio_extraordinario'],
                            anu['data_fim_extraordinario'],
                            anu['data_pagamento']
                        )
                        dias_restantes = utils.obter_dias_restantes(anu['data_fim_ordinario'], anu['data_pagamento'])
                        emoji = utils.criar_emoji_status(status_calc)
                        status_disp = f"{emoji} {status_calc.upper()}"

                    dados_tabela.append({
                        "Identificação Fiscal": nome_taxa,
                        "Início Ordinário": utils.formatar_data(anu['data_inicio_ordinario']),
                        "Fim Ordinário": utils.formatar_data(anu['data_fim_ordinario']),
                        "Dias Restantes": dias_restantes,
                        "Status Atual": status_disp,
                        "Data do Pagamento": utils.formatar_data(anu['data_pagamento']) if anu['data_pagamento'] else "-"
                    })

                st.dataframe(pd.DataFrame(dados_tabela), use_container_width=True, hide_index=True)

                st.divider()
                st.subheader("⚙️ Ações e Quitação de Taxas")
                col_p1, col_p2, col_p3 = st.columns(3)
                with col_p1:
                    taxa_selecionada = st.selectbox("Selecione a Taxa/Período", anuidades['numero_anuidade'].tolist())
                with col_p2:
                    data_quitar = st.date_input("Data do Pagamento", value=datetime.now().date())
                with col_p3:
                    st.write("")
                    st.write("")
                    if st.button("💰 Registrar Quitação", use_container_width=True, type="primary"):
                        db.atualizar_status_anuidade(ativo_id, taxa_selecionada, "pago", data_quitar.strftime("%Y-%m-%d"))
                        st.success("Pagamento registrado!")
                        st.rerun()

            st.divider()
            if st.button("🗑️ Deletar Ativo permanentemente", type="secondary", use_container_width=True):
                if st.checkbox("Confirmo que desejo apagar esse ativo e todas as suas taxas correlacionadas."):
                    db.deletar_patente(ativo_id)
                    st.success("Deletado com sucesso.")
                    st.rerun()

elif pagina == "📤 Importar Excel":
    st.title("📤 Importar via Planilha")
    st.info("""
    📋 Adicionamos suporte completo à importação de Softwares e Desenhos Industriais no Excel.
    Novas Colunas aceitas:
    - **tipo** (Valores aceitos: *Patente*, *Software*, *Desenho Industrial*)
    - **linguagem** (Para ativos do tipo *Software*)
    """)

    arquivo_excel = st.file_uploader("Selecione o arquivo Excel (.xlsx)", type="xlsx")

    if arquivo_excel:
        if st.button("📥 Executar Importação", use_container_width=True, type="primary"):
            resultados = db.importar_excel(arquivo_excel)
            st.success(f"Processamento concluído. {len(resultados)} registros analisados.")

elif pagina == "🤖 Análise IA":
    st.title("🤖 Análise Inteligente de Ativos (IA)")
    df_patentes = db.obter_patentes()

    if len(df_patentes) == 0:
        st.warning("Banco de dados vazio.")
    else:
        pergunta = st.text_input("Pergunte algo como: 'Quantos softwares temos cadastrados?' ou 'Quais são os desenhos industriais?'")
        if st.button("Analisar Pergunta") and pergunta:
            res = ai_analyzer.analisar_pergunta(df_patentes, pergunta)
            st.info(res)

elif pagina == "📄 Gerar Relatórios":
    st.title("📄 Relatórios e Exportação")
    df_patentes = db.obter_patentes()

    if len(df_patentes) == 0:
        st.warning("Banco de dados vazio.")
    else:
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            if st.button("📋 Baixar Relatório de Ativos (PDF)", use_container_width=True):
                pdf = report_generator.gerar_relatorio_completo(df_patentes)
                st.download_button("Clique para baixar", pdf, "ativos_pi_completo.pdf", "application/pdf")
        with col_r2:
            if st.button("📊 Exportar Banco para Excel", use_container_width=True):
                excel = report_generator.exportar_para_excel(df_patentes)
                st.download_button("Clique para baixar", excel, "ativos_pi_export.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
