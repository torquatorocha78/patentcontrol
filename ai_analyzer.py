import pandas as pd
import database as db
from datetime import datetime
import utils

def analisar_pergunta(df_patentes, pergunta):
    """
    Análise inteligente de perguntas sobre Ativos de PI (Patentes, Softwares e Desenhos)
    """
    pergunta_lower = pergunta.lower()

    # Tratativa específica para Softwares e Linguagens
    if "software" in pergunta_lower or "programa" in pergunta_lower:
        softwares = df_patentes[df_patentes['tipo'].str.lower() == 'software'] if 'tipo' in df_patentes else pd.DataFrame()
        total_s = len(softwares)

        # Mapeamento de linguagens
        if 'linguagem' in softwares.columns and total_s > 0:
            ling_counts = softwares['linguagem'].value_counts()
            detalhe_ling = "\n".join([f"- **{ling}**: {qtd} softwares" for ling, qtd in ling_counts.items()])
        else:
            detalhe_ling = "Nenhuma linguagem informada."

        return f"""
        💻 **Softwares de Computador**:
        - Total cadastrado: {total_s}
        - Divisão por linguagens de programação:
        {detalhe_ling}
        """

    # Tratativa específica para Desenhos Industriais
    if "desenho" in pergunta_lower or "industrial" in pergunta_lower or "di" in pergunta_lower:
        desenhos = df_patentes[df_patentes['tipo'].str.lower() == 'desenho industrial'] if 'tipo' in df_patentes else pd.DataFrame()
        return f"🎨 **Desenhos Industriais**: Encontramos um total de **{len(desenhos)}** desenhos industriais cadastrados no IFSC."

    # Contar concedidos genéricos (ou patentes concedidas)
    if "concedida" in pergunta_lower or "concessão" in pergunta_lower:
        total = len(df_patentes)
        concedidas = len(df_patentes[df_patentes['data_concessao'].notna()])
        pendentes = total - concedidas
        return f"""
        **Ativos Concedidos (Patentes, Softwares e Desenhos):**
        - Total geral de ativos: {total}
        - Ativos concedidos/homologados: {concedidas}
        - Ativos pendentes: {pendentes}
        - Taxa global de concessão: {(concedidas/total*100) if total > 0 else 0:.1f}%
        """

    # Ativos vencidos
    if "vencida" in pergunta_lower or "expirada" in pergunta_lower or "vencido" in pergunta_lower:
        vencidas = 0
        for _, patente in df_patentes.iterrows():
            anuidades = db.obter_anuidades(patente['id'])
            for _, anu in anuidades.iterrows():
                if anu['status'] != 'nao_pagar':
                    status = utils.calcular_status_anuidade(
                        anu['data_inicio_ordinario'],
                        anu['data_fim_ordinario'],
                        anu['data_inicio_extraordinario'],
                        anu['data_fim_extraordinario'],
                        anu['data_pagamento']
                    )
                    if status == 'vermelho':
                        vencidas += 1
        return f"🚨 **Prazos em Atraso**: Há {vencidas} taxas/anuidades vencidas que necessitam de quitação urgente!"

    # Contagem total
    if "quantas" in pergunta_lower or "total" in pergunta_lower or "ativos" in pergunta_lower:
        # Se for contagem pura
        tipos_count = df_patentes['tipo'].value_counts() if 'tipo' in df_patentes else pd.Series()
        resumo = "\n".join([f"- **{tipo}**: {qtd}" for tipo, qtd in tipos_count.items()])
        return f"""
        📊 **Total Geral de Ativos**: {len(df_patentes)} registros cadastrados.

        **Distribuição de Ativos:**
        {resumo}
        """

    # Resposta padrão de fallback
    return f"Não compreendi a pergunta, mas posso analisar os {len(df_patentes)} ativos de PI. Tente perguntar sobre 'softwares', 'desenhos industriais', 'vencidos' ou 'concedidos'!"


def gerar_estatisticas(df_patentes):
    total = len(df_patentes)
    concedidas = len(df_patentes[df_patentes['data_concessao'].notna()])

    stats = f"""
    ### 📊 Estatísticas Gerais de Propriedade Intelectual

    **Total de Ativos Cadastrados:** {total}
    **Homologados/Concedidos:** {concedidas}

    **Divisão por categoria:**
    """
    if 'tipo' in df_patentes.columns:
        for t, count in df_patentes['tipo'].value_counts().items():
            stats += f"\n- {t}: {count}"

    return stats


def patentes_por_gestor(df_patentes):
    output = "### 🎯 Ativos por Gestor\n\n"
    gestores = df_patentes['gestor'].fillna('IFSC').str.upper().unique()

    for gestor in sorted(gestores):
        count = len(df_patentes[
            ((df_patentes['gestor'].isna()) & (gestor == 'IFSC')) |
            (df_patentes['gestor'].str.upper() == gestor)
        ])
        output += f"- **{gestor}**: {count} ativos cadastrados\n"

    return output


def gerar_alertas(df_patentes):
    alertas = "### ⚠️ Alertas Urgentes de Taxas\n\n"
    alertas_count = 0

    for _, patente in df_patentes.iterrows():
        anuidades = db.obter_anuidades(patente['id'])
        for _, anu in anuidades.iterrows():
            if anu['status'] == 'nao_pagar':
                continue

            status = utils.calcular_status_anuidade(
                anu['data_inicio_ordinario'],
                anu['data_fim_ordinario'],
                anu['data_inicio_extraordinario'],
                anu['data_fim_extraordinario'],
                anu['data_pagamento']
            )

            if status == 'vermelho':
                alertas += f"- 🚨 **{patente['numero_patente']}** ({patente.get('tipo','Patente')}) - Taxa vencida!\n"
                alertas_count += 1
            elif status == 'amarelo':
                dias = utils.obter_dias_restantes(anu['data_fim_ordinario'])
                alertas += f"- ⚠️ **{patente['numero_patente']}** - Próximo vencimento em {dias} dias\n"
                alertas_count += 1

    if alertas_count == 0:
        alertas += "✅ Todos os pagamentos e taxas de propriedade intelectual estão em dia!"

    return alertas
