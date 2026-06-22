import pandas as pd
import database as db
from datetime import datetime
import utils
from io import BytesIO
import io

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

def gerar_relatorio_completo(df_patentes):
    """
    Gera relatório completo em PDF com todas as patentes e anuidades
    """
    if not REPORTLAB_AVAILABLE:
        return criar_pdf_fallback(df_patentes)
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    story = []
    styles = getSampleStyleSheet()
    
    # Título
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#003366'),
        spaceAfter=10,
        alignment=1
    )
    
    story.append(Paragraph("🏛️ Gestão de Patentes do IFSC", title_style))
    story.append(Paragraph("Relatório Completo de Patentes", styles['Heading2']))
    story.append(Spacer(1, 0.3*inch))
    
    # Resumo
    total = len(df_patentes)
    concedidas = len(df_patentes[df_patentes['data_concessao'].notna()])
    
    story.append(Paragraph(f"<b>Data do Relatório:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    story.append(Paragraph(f"<b>Total de Patentes:</b> {total}", styles['Normal']))
    story.append(Paragraph(f"<b>Patentes Concedidas:</b> {concedidas}", styles['Normal']))
    story.append(Spacer(1, 0.2*inch))
    
    # Tabela de patentes
    story.append(Paragraph("Patentes Cadastradas", styles['Heading3']))
    
    tabela_dados = [['Nº Patente', 'Deposito', 'Concessão', 'Gestor', 'Status']]
    for _, patente in df_patentes.iterrows():
        tabela_dados.append([
            patente['numero_patente'][:20],
            utils.formatar_data(patente['data_deposito']),
            utils.formatar_data(patente['data_concessao']) if patente['data_concessao'] else '-',
            patente.get('gestor', 'N/A')[:15],
            patente.get('status', 'Ativo')
        ])
    
    table = Table(tabela_dados, colWidths=[2*inch, 1*inch, 1*inch, 1.2*inch, 1*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    story.append(table)
    story.append(Spacer(1, 0.3*inch))
    
    # Detalhes de anuidades
    story.append(PageBreak())
    story.append(Paragraph("Detalhamento de Anuidades", styles['Heading2']))
    story.append(Spacer(1, 0.2*inch))
    
    for _, patente in df_patentes.iterrows():
        story.append(Paragraph(f"Patente: {patente['numero_patente']}", styles['Heading3']))
        
        anuidades = db.obter_anuidades(patente['id'])
        anuidade_dados = [['Anuidade', 'Fim Ordinário', 'Status', 'Pagamento']]
        
        for _, anu in anuidades.iterrows():
            if anu['status'] == 'nao_pagar':
                status_display = '⛔ NÃO PAGAR'
            else:
                status = utils.calcular_status_anuidade(
                    anu['data_inicio_ordinario'],
                    anu['data_fim_ordinario'],
                    anu['data_inicio_extraordinario'],
                    anu['data_fim_extraordinario'],
                    anu['data_pagamento']
                )
                status_display = status.upper()
            
            anuidade_dados.append([
                str(anu['numero_anuidade']),
                utils.formatar_data(anu['data_fim_ordinario']),
                status_display,
                utils.formatar_data(anu['data_pagamento']) if anu['data_pagamento'] else '-'
            ])
        
        table_anu = Table(anuidade_dados, colWidths=[1*inch, 1.5*inch, 1.5*inch, 1.5*inch])
        table_anu.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#666666')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(table_anu)
        story.append(Spacer(1, 0.2*inch))
    
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def gerar_relatorio_anuidades(df_patentes):
    """
    Gera relatório focado em anuidades
    """
    if not REPORTLAB_AVAILABLE:
        return criar_pdf_fallback(df_patentes)
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    story = []
    styles = getSampleStyleSheet()
    
    story.append(Paragraph("🏛️ Gestão de Patentes do IFSC", styles['Heading1']))
    story.append(Paragraph("Relatório de Anuidades", styles['Heading2']))
    story.append(Spacer(1, 0.3*inch))
    
    anuidade_dados = [['Patente', 'Anuidade', 'Fim Ordinário', 'Status', 'Dias Restantes']]
    
    for _, patente in df_patentes.iterrows():
        anuidades = db.obter_anuidades(patente['id'])
        for _, anu in anuidades.iterrows():
            if anu['status'] == 'nao_pagar':
                status_display = '⛔ NÃO PAGAR'
                dias = '-'
            else:
                status = utils.calcular_status_anuidade(
                    anu['data_inicio_ordinario'],
                    anu['data_fim_ordinario'],
                    anu['data_inicio_extraordinario'],
                    anu['data_fim_extraordinario'],
                    anu['data_pagamento']
                )
                status_display = status.upper()
                dias = str(utils.obter_dias_restantes(anu['data_fim_ordinario']))
            
            anuidade_dados.append([
                patente['numero_patente'][:20],
                str(anu['numero_anuidade']),
                utils.formatar_data(anu['data_fim_ordinario']),
                status_display,
                dias
            ])
    
    table = Table(anuidade_dados, colWidths=[1.5*inch, 0.8*inch, 1.2*inch, 1.2*inch, 1.2*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def gerar_relatorio_alertas(df_patentes):
    """
    Gera relatório focado em alertas e anuidades vencidas
    """
    if not REPORTLAB_AVAILABLE:
        return criar_pdf_fallback(df_patentes)
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    story = []
    styles = getSampleStyleSheet()
    
    story.append(Paragraph("🏛️ Gestão de Patentes do IFSC", styles['Heading1']))
    story.append(Paragraph("Relatório de Alertas", styles['Heading2']))
    story.append(Spacer(1, 0.3*inch))
    
    alertas_vencidas = []
    alertas_atencao = []
    
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
                alertas_vencidas.append([
                    patente['numero_patente'][:20],
                    anu['numero_anuidade'],
                    utils.formatar_data(anu['data_fim_ordinario'])
                ])
            elif status == 'amarelo':
                alertas_atencao.append([
                    patente['numero_patente'][:20],
                    anu['numero_anuidade'],
                    utils.obter_dias_restantes(anu['data_fim_ordinario']),
                    utils.formatar_data(anu['data_fim_ordinario'])
                ])
    
    if alertas_vencidas:
        story.append(Paragraph("🚨 Anuidades Vencidas (Ação Urgente!)", styles['Heading3']))
        tabela_vencidas = [['Patente', 'Anuidade', 'Data Vencimento']] + alertas_vencidas
        table = Table(tabela_vencidas, colWidths=[2*inch, 1*inch, 1.5*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.red),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(table)
        story.append(Spacer(1, 0.3*inch))
    
    if alertas_atencao:
        story.append(Paragraph("⚠️ Anuidades para Atenção (30 dias para vencer)", styles['Heading3']))
        tabela_atencao = [['Patente', 'Anuidade', 'Dias Restantes', 'Data Vencimento']] + alertas_atencao
        table = Table(tabela_atencao, colWidths=[2*inch, 1*inch, 1.2*inch, 1.3*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.orange),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(table)
    
    if not alertas_vencidas and not alertas_atencao:
        story.append(Paragraph("✅ Nenhum alerta! Todas as anuidades estão em dia.", styles['Normal']))
    
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def exportar_para_excel(df_patentes):
    """
    Exporta dados para Excel
    """
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_patentes.to_excel(writer, sheet_name='Patentes', index=False)
        
        # Adicionar sheet de anuidades
        all_anuidades = []
        for _, patente in df_patentes.iterrows():
            anuidades = db.obter_anuidades(patente['id'])
            for _, anu in anuidades.iterrows():
                all_anuidades.append({
                    'Patente': patente['numero_patente'],
                    'Anuidade': anu['numero_anuidade'],
                    'Fim Ordinário': utils.formatar_data(anu['data_fim_ordinario']),
                    'Status': anu['status'],
                    'Pagamento': utils.formatar_data(anu['data_pagamento']) if anu['data_pagamento'] else '-'
                })
        
        if all_anuidades:
            df_anuidades = pd.DataFrame(all_anuidades)
            df_anuidades.to_excel(writer, sheet_name='Anuidades', index=False)
    
    output.seek(0)
    return output.getvalue()

def exportar_para_csv(df_patentes):
    """
    Exporta dados para CSV
    """
    output = io.StringIO()
    df_patentes.to_csv(output, index=False)
    return output.getvalue().encode('utf-8')

def criar_pdf_fallback(df_patentes):
    """
    Criar PDF simples sem reportlab (fallback)
    """
    # Se reportlab não estiver disponível, retornar aviso
    texto = "Instale reportlab para gerar PDFs: pip install reportlab"
    return texto.encode('utf-8')
