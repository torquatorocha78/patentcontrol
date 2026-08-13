# database.py - SIGPI-IF / banco SQLite relacional
import sqlite3
import unicodedata
from datetime import date
from pathlib import Path
import pandas as pd

DB_NAME = 'patentes.db'


def conectar():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def _valor_limpo(v):
    if v is None: return None
    try:
        if pd.isna(v): return None
    except Exception: pass
    return v.strip() if isinstance(v, str) and v.strip() else (v if not isinstance(v, str) else None)


def _normalizar_coluna(c):
    s = ''.join(x for x in unicodedata.normalize('NFKD', str(c).strip().lower()) if not unicodedata.combining(x))
    for x in '/\\-().:;': s = s.replace(x, ' ')
    return '_'.join(s.split())


def _parse_data(v):
    v = _valor_limpo(v)
    if v is None: return None
    try:
        if not isinstance(v, str) and hasattr(v, 'date'): return v.date().isoformat()
        s = str(v).strip()
        if not s: return None
        if len(s) >= 10 and s[4] == '-' and s[7] == '-': return pd.to_datetime(s).date().isoformat()
        return pd.to_datetime(s, dayfirst=True).date().isoformat()
    except Exception: return str(v)


def _normalizar_status(v):
    if not _valor_limpo(v): return 'Ativo'
    s = str(v).strip(); k = _normalizar_coluna(s)
    mapa = {'patente_concedida':'Patente Concedida','patente_concedda':'Patente Concedida','concedido':'Patente Concedida','concedida':'Patente Concedida','tramitando_normal':'Tramitando Normal','infederimento':'Indeferimento','indeferimento':'Indeferimento','recurso_contra_indeferimento':'Recurso contra indeferimento','pedido_de_exame':'Pedido de exame','arquivado':'Arquivado','desistencia':'Desistência'}
    return mapa.get(k, s)


def _split(v):
    if not v: return []
    s = str(v).replace('\r','\n')
    for sep in [';','/','|']: s = s.replace(sep,'\n')
    return list(dict.fromkeys(x.strip() for x in s.split('\n') if x.strip()))


def _nao_pagar(gestor, status):
    g = _normalizar_coluna(gestor or '')
    if g and g not in ('ifsc','instituto_federal_de_santa_catarina','instituto_federal_sc'):
        return True
    s = _normalizar_coluna(status or '')
    return any(x in s for x in ('indefer','arquiv','desist'))


def init_database():
    conn = conectar(); cur = conn.cursor()
    # Mantém compatibilidade com a base antiga: as colunas legado titular/inventores
    # continuam existindo se já estiverem na tabela, mas o relacionamento oficial
    # passa a ser feito pelas tabelas normalizadas.
    cur.executescript('''
    CREATE TABLE IF NOT EXISTS patentes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      numero_patente TEXT NOT NULL UNIQUE,
      data_deposito DATE NOT NULL,
      data_concessao DATE,
      titulo TEXT, descricao TEXT, gestor TEXT,
      status TEXT NOT NULL DEFAULT 'Ativo', campus TEXT, atributos TEXT,
      data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS inventores (
      id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL UNIQUE,
      cpf TEXT, email TEXT, instituicao TEXT
    );
    CREATE TABLE IF NOT EXISTS patente_inventores (
      id INTEGER PRIMARY KEY AUTOINCREMENT, patente_id INTEGER NOT NULL,
      inventor_id INTEGER NOT NULL, ordem INTEGER DEFAULT 1, principal INTEGER DEFAULT 0,
      FOREIGN KEY(patente_id) REFERENCES patentes(id) ON DELETE CASCADE,
      FOREIGN KEY(inventor_id) REFERENCES inventores(id) ON DELETE RESTRICT,
      UNIQUE(patente_id,inventor_id)
    );
    CREATE TABLE IF NOT EXISTS titulares (
      id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL UNIQUE,
      documento TEXT, tipo TEXT, email TEXT
    );
    CREATE TABLE IF NOT EXISTS patente_titulares (
      id INTEGER PRIMARY KEY AUTOINCREMENT, patente_id INTEGER NOT NULL,
      titular_id INTEGER NOT NULL, percentual REAL, principal INTEGER DEFAULT 0,
      ordem INTEGER DEFAULT 1,
      FOREIGN KEY(patente_id) REFERENCES patentes(id) ON DELETE CASCADE,
      FOREIGN KEY(titular_id) REFERENCES titulares(id) ON DELETE RESTRICT,
      UNIQUE(patente_id,titular_id)
    );
    CREATE TABLE IF NOT EXISTS anuidades (
      id INTEGER PRIMARY KEY AUTOINCREMENT, patente_id INTEGER NOT NULL,
      numero_anuidade INTEGER NOT NULL, data_inicio_ordinario DATE,
      data_fim_ordinario DATE, data_inicio_extraordinario DATE,
      data_fim_extraordinario DATE, status TEXT DEFAULT 'pendente',
      data_pagamento DATE, observacao TEXT,
      FOREIGN KEY(patente_id) REFERENCES patentes(id) ON DELETE CASCADE,
      UNIQUE(patente_id,numero_anuidade)
    );
    CREATE TABLE IF NOT EXISTS documentos (
      id INTEGER PRIMARY KEY AUTOINCREMENT, patente_id INTEGER NOT NULL,
      tipo TEXT, nome_arquivo TEXT NOT NULL, caminho TEXT, descricao TEXT,
      data_documento DATE, data_upload TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(patente_id) REFERENCES patentes(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS historico (
      id INTEGER PRIMARY KEY AUTOINCREMENT, patente_id INTEGER NOT NULL,
      data_evento TIMESTAMP DEFAULT CURRENT_TIMESTAMP, tipo_evento TEXT NOT NULL,
      descricao TEXT, usuario TEXT,
      FOREIGN KEY(patente_id) REFERENCES patentes(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_patentes_status ON patentes(status);
    CREATE INDEX IF NOT EXISTS idx_patentes_gestor ON patentes(gestor);
    CREATE INDEX IF NOT EXISTS idx_anuidades_status ON anuidades(status);
    CREATE INDEX IF NOT EXISTS idx_anuidades_patente ON anuidades(patente_id);
    CREATE INDEX IF NOT EXISTS idx_historico_patente ON historico(patente_id);
    ''')
    cols = {r[1] for r in cur.execute('PRAGMA table_info(patentes)')}
    for col in ('titulo','campus','atributos','data_criacao','data_atualizacao'):
        if col not in cols:
            typ = 'TIMESTAMP' if col.startswith('data_') else 'TEXT'
            cur.execute(f'ALTER TABLE patentes ADD COLUMN {col} {typ}')
    # migração de colunas legadas, se existirem
    cols = {r[1] for r in cur.execute('PRAGMA table_info(patentes)')}
    for col in ('titular','inventores'):
        if col not in cols: cur.execute(f'ALTER TABLE patentes ADD COLUMN {col} TEXT')
    conn.commit(); _migrar_legado(conn); conn.close(); garantir_anuidades_existentes()


def _migrar_legado(conn):
    cur=conn.cursor()
    rows=cur.execute('SELECT id,titular,inventores,gestor,status FROM patentes').fetchall()
    for pid,tit,invs,gest,status in rows:
        for ordem,nome in enumerate(_split(tit),1):
            cur.execute('INSERT OR IGNORE INTO titulares(nome) VALUES(?)',(nome,))
            tid=cur.execute('SELECT id FROM titulares WHERE nome=?',(nome,)).fetchone()[0]
            cur.execute('INSERT OR IGNORE INTO patente_titulares(patente_id,titular_id,ordem,principal) VALUES(?,?,?,?)',(pid,tid,ordem,1 if ordem==1 else 0))
        for ordem,nome in enumerate(_split(invs),1):
            cur.execute('INSERT OR IGNORE INTO inventores(nome) VALUES(?)',(nome,))
            iid=cur.execute('SELECT id FROM inventores WHERE nome=?',(nome,)).fetchone()[0]
            cur.execute('INSERT OR IGNORE INTO patente_inventores(patente_id,inventor_id,ordem,principal) VALUES(?,?,?,?)',(pid,iid,ordem,1 if ordem==1 else 0))
        if _nao_pagar(gest,status): cur.execute("UPDATE anuidades SET status='nao_pagar' WHERE patente_id=? AND status<>'pago'",(pid,))
    conn.commit()


def obter_patentes():
    conn=conectar()
    q="""SELECT p.id,p.numero_patente,p.data_deposito,p.data_concessao,p.titulo,p.descricao,p.gestor,p.status,p.campus,p.atributos,p.data_criacao,p.data_atualizacao, COALESCE((SELECT GROUP_CONCAT(i.nome,' / ') FROM patente_inventores pi JOIN inventores i ON i.id=pi.inventor_id WHERE pi.patente_id=p.id ORDER BY pi.ordem),'') AS inventores, COALESCE((SELECT GROUP_CONCAT(t.nome,' / ') FROM patente_titulares pt JOIN titulares t ON t.id=pt.titular_id WHERE pt.patente_id=p.id ORDER BY pt.principal DESC,pt.ordem),'') AS titular FROM patentes p ORDER BY p.id"""
    df=pd.read_sql_query(q,conn); conn.close(); return df


def obter_anuidades(patente_id):
    conn=conectar(); cur=conn.cursor(); r=cur.execute('SELECT data_deposito,gestor,status FROM patentes WHERE id=?',(int(patente_id),)).fetchone()
    if r:
        _garantir_anuidades_patente(cur,int(patente_id),r[0])
        if _nao_pagar(r[1],r[2]): cur.execute("UPDATE anuidades SET status='nao_pagar' WHERE patente_id=? AND status NOT IN('pago','nao_pagar')",(int(patente_id),))
        conn.commit()
    df=pd.read_sql_query('SELECT * FROM anuidades WHERE patente_id=? ORDER BY numero_anuidade',conn,params=(int(patente_id),)); conn.close(); return df


def _datas_anuidade(dep,n):
    inicio=pd.to_datetime(dep); ini=inicio+pd.DateOffset(years=n-1); fim=ini+pd.DateOffset(months=3); ext=fim; fimext=ext+pd.DateOffset(months=6)
    return ini.date(),fim.date(),ext.date(),fimext.date()


def _garantir_anuidades_patente(cur,pid,dep):
    if not dep:return
    existentes={r[0] for r in cur.execute('SELECT numero_anuidade FROM anuidades WHERE patente_id=?',(pid,))}
    for n in range(1,21):
        if n in existentes:continue
        a,b,c,d=_datas_anuidade(dep,n)
        cur.execute('INSERT INTO anuidades(patente_id,numero_anuidade,data_inicio_ordinario,data_fim_ordinario,data_inicio_extraordinario,data_fim_extraordinario,status) VALUES(?,?,?,?,?,?,?)',(pid,n,a,b,c,d,'pendente'))


def garantir_anuidades_existentes():
    conn=conectar();cur=conn.cursor()
    for pid,dep,g,s in cur.execute('SELECT id,data_deposito,gestor,status FROM patentes'):
        _garantir_anuidades_patente(cur,pid,dep)
        if _nao_pagar(g,s):cur.execute("UPDATE anuidades SET status='nao_pagar' WHERE patente_id=? AND status NOT IN('pago','nao_pagar')",(pid,))
    conn.commit();conn.close()


def _sync_people(cur,pid,titular,inventores):
    cur.execute('DELETE FROM patente_inventores WHERE patente_id=?',(pid,));cur.execute('DELETE FROM patente_titulares WHERE patente_id=?',(pid,))
    for ordem,nome in enumerate(_split(inventores),1):
        cur.execute('INSERT OR IGNORE INTO inventores(nome) VALUES(?)',(nome,)); iid=cur.execute('SELECT id FROM inventores WHERE nome=?',(nome,)).fetchone()[0]
        cur.execute('INSERT INTO patente_inventores(patente_id,inventor_id,ordem,principal) VALUES(?,?,?,?)',(pid,iid,ordem,1 if ordem==1 else 0))
    for ordem,nome in enumerate(_split(titular),1):
        cur.execute('INSERT OR IGNORE INTO titulares(nome) VALUES(?)',(nome,)); tid=cur.execute('SELECT id FROM titulares WHERE nome=?',(nome,)).fetchone()[0]
        cur.execute('INSERT INTO patente_titulares(patente_id,titular_id,ordem,principal) VALUES(?,?,?,?)',(pid,tid,ordem,1 if ordem==1 else 0))


def adicionar_patente(numero,data_dep,data_conc,descricao,titular,gestor=None,status_patente='Ativo',titulo=None,inventores=None,campus=None,atributos=None):
    conn=conectar();cur=conn.cursor()
    try:
        status_patente=_normalizar_status(status_patente); dep=_parse_data(data_dep); conc=_parse_data(data_conc)
        cur.execute('INSERT INTO patentes(numero_patente,data_deposito,data_concessao,titulo,descricao,gestor,status,campus,atributos) VALUES(?,?,?,?,?,?,?,?,?)',(str(numero).strip(),dep,conc,_valor_limpo(titulo),_valor_limpo(descricao),_valor_limpo(gestor),status_patente,_valor_limpo(campus),_valor_limpo(atributos)))
        pid=cur.lastrowid;_sync_people(cur,pid,titular,inventores);_garantir_anuidades_patente(cur,pid,dep)
        if _nao_pagar(gestor,status_patente):cur.execute("UPDATE anuidades SET status='nao_pagar' WHERE patente_id=?",(pid,))
        cur.execute("INSERT INTO historico(patente_id,tipo_evento,descricao) VALUES(?,?,?)",(pid,'CADASTRO','Patente cadastrada no SIGPI-IF'))
        conn.commit();return True,'Patente cadastrada com sucesso.'
    except Exception as e:conn.rollback();return False,str(e)
    finally:conn.close()


def atualizar_patente(patente_id,numero,data_dep,data_conc,descricao,titular,gestor=None,status_patente='Ativo',titulo=None,inventores=None,campus=None,atributos=None):
    conn=conectar();cur=conn.cursor()
    try:
        status_patente=_normalizar_status(status_patente);dep=_parse_data(data_dep);conc=_parse_data(data_conc)
        cur.execute('UPDATE patentes SET numero_patente=?,data_deposito=?,data_concessao=?,titulo=?,descricao=?,gestor=?,status=?,campus=?,atributos=?,data_atualizacao=CURRENT_TIMESTAMP WHERE id=?',(numero,dep,conc,_valor_limpo(titulo),_valor_limpo(descricao),_valor_limpo(gestor),status_patente,_valor_limpo(campus),_valor_limpo(atributos),int(patente_id)))
        _sync_people(cur,int(patente_id),titular,inventores);_garantir_anuidades_patente(cur,int(patente_id),dep)
        if _nao_pagar(gestor,status_patente):cur.execute("UPDATE anuidades SET status='nao_pagar' WHERE patente_id=? AND status NOT IN('pago','nao_pagar')",(int(patente_id),))
        cur.execute("INSERT INTO historico(patente_id,tipo_evento,descricao) VALUES(?,?,?)",(int(patente_id),'ATUALIZACAO','Dados da patente atualizados'))
        conn.commit();return True,'Patente atualizada com sucesso.'
    except Exception as e:conn.rollback();return False,str(e)
    finally:conn.close()


def salvar_patente_importada(dados):
    conn=conectar();r=conn.execute('SELECT id FROM patentes WHERE numero_patente=?',(dados['numero'],)).fetchone();conn.close()
    if r:
        ok,msg=atualizar_patente(r[0],**dados);return ok,('Atualizada: '+msg if ok else msg)
    ok,msg=adicionar_patente(**dados);return ok,('Importada: '+msg if ok else msg)


def atualizar_status_anuidade(patente_id,numero_anuidade,novo_status,data_pagamento=None):
    conn=conectar();
    try:
        if novo_status=='pago': conn.execute("UPDATE anuidades SET status='pago',data_pagamento=? WHERE patente_id=? AND numero_anuidade=?",(_parse_data(data_pagamento),patente_id,numero_anuidade))
        elif novo_status=='nao_pagar': conn.execute("UPDATE anuidades SET status='nao_pagar',data_pagamento=NULL WHERE patente_id=? AND numero_anuidade=?",(patente_id,numero_anuidade))
        else: conn.execute("UPDATE anuidades SET status='pendente',data_pagamento=NULL WHERE patente_id=? AND numero_anuidade=?",(patente_id,numero_anuidade))
        conn.execute("INSERT INTO historico(patente_id,tipo_evento,descricao) VALUES(?,?,?)",(patente_id,'ANUIDADE',f'Anuidade {numero_anuidade}: {novo_status}'));conn.commit()
    finally:conn.close()


def deletar_patente(patente_id):
    conn=conectar();conn.execute('DELETE FROM patentes WHERE id=?',(int(patente_id),));conn.commit();conn.close()


def registrar_historico(patente_id,tipo_evento,descricao,usuario=None):
    conn=conectar();conn.execute('INSERT INTO historico(patente_id,tipo_evento,descricao,usuario) VALUES(?,?,?,?)',(patente_id,tipo_evento,descricao,usuario));conn.commit();conn.close()


def obter_dataset_anuidades():
    conn=conectar();q='''SELECT p.id patente_id,p.numero_patente,p.titulo,p.data_deposito,p.data_concessao,p.gestor,p.status status_patente,p.campus,a.numero_anuidade,a.data_inicio_ordinario,a.data_fim_ordinario,a.data_inicio_extraordinario,a.data_fim_extraordinario,a.status status_anuidade,a.data_pagamento,a.observacao,COALESCE((SELECT GROUP_CONCAT(i.nome,' / ') FROM patente_inventores pi JOIN inventores i ON i.id=pi.inventor_id WHERE pi.patente_id=p.id),'') inventores,COALESCE((SELECT GROUP_CONCAT(t.nome,' / ') FROM patente_titulares pt JOIN titulares t ON t.id=pt.titular_id WHERE pt.patente_id=p.id),'') titular FROM patentes p JOIN anuidades a ON a.patente_id=p.id ORDER BY p.numero_patente,a.numero_anuidade''';df=pd.read_sql_query(q,conn);conn.close();return df


def obter_inventores(patente_id=None):
    conn=conectar();q='SELECT i.*,pi.ordem,pi.principal FROM inventores i JOIN patente_inventores pi ON pi.inventor_id=i.id WHERE pi.patente_id=? ORDER BY pi.ordem';df=pd.read_sql_query(q,conn,params=(patente_id,)) if patente_id else pd.read_sql_query('SELECT * FROM inventores ORDER BY nome',conn);conn.close();return df

def obter_titulares(patente_id=None):
    conn=conectar();q='SELECT t.*,pt.ordem,pt.principal,pt.percentual FROM titulares t JOIN patente_titulares pt ON pt.titular_id=t.id WHERE pt.patente_id=? ORDER BY pt.ordem';df=pd.read_sql_query(q,conn,params=(patente_id,)) if patente_id else pd.read_sql_query('SELECT * FROM titulares ORDER BY nome',conn);conn.close();return df

def obter_documentos(patente_id):
    conn=conectar();df=pd.read_sql_query('SELECT * FROM documentos WHERE patente_id=? ORDER BY id DESC',conn,params=(patente_id,));conn.close();return df

def obter_historico(patente_id):
    conn=conectar();df=pd.read_sql_query('SELECT * FROM historico WHERE patente_id=? ORDER BY data_evento DESC,id DESC',conn,params=(patente_id,));conn.close();return df


def _map_excel(df):
    cols={_normalizar_coluna(c):c for c in df.columns}
    def f(*names):
        for n in names:
            if _normalizar_coluna(n) in cols:return cols[_normalizar_coluna(n)]
        return None
    return {'numero':f('numero_patente','número patente','numero patente','patente'),'data_dep':f('data_deposito','data depósito','data deposito'),'data_conc':f('data_concessao','data concessão','data concessao'),'titulo':f('titulo','título'),'descricao':f('resumo','descricao','descrição'),'inventores':f('nome dos inventores','inventores','nome_dos_inventores'),'titular':f('depositante titular','depositante/ titular','titular','depositante'),'gestor':f('gestor'),'status':f('status do pedido','status','situacao','situação'),'campus':f('campus'),'atributos':f('atributos','atributo')}


def importar_excel(arquivo_excel):
    res=[]
    try:
        df=pd.read_excel(arquivo_excel);m=_map_excel(df)
        for _,r in df.iterrows():
            n=_valor_limpo(r.get(m['numero'])) if m['numero'] else None;dep=_parse_data(r.get(m['data_dep'])) if m['data_dep'] else None
            if not n or not dep:res.append((n or 'SEM_NUMERO',False,'Número da patente ou data de depósito ausente'));continue
            d={'numero':str(n),'data_dep':dep,'data_conc':_parse_data(r.get(m['data_conc'])) if m['data_conc'] else None,'descricao':_valor_limpo(r.get(m['descricao'])) if m['descricao'] else None,'titular':_valor_limpo(r.get(m['titular'])) if m['titular'] else None,'gestor':_valor_limpo(r.get(m['gestor'])) if m['gestor'] else None,'status_patente':_normalizar_status(r.get(m['status'])) if m['status'] else 'Ativo','titulo':_valor_limpo(r.get(m['titulo'])) if m['titulo'] else None,'inventores':_valor_limpo(r.get(m['inventores'])) if m['inventores'] else None,'campus':_valor_limpo(r.get(m['campus'])) if m['campus'] else None,'atributos':_valor_limpo(r.get(m['atributos'])) if m['atributos'] else None}
            ok,msg=salvar_patente_importada(d);res.append((n,ok,msg))
    except Exception as e:res.append(('ERRO_GERAL',False,str(e)))
    return res


def analisar_inconsistencias_excel(arquivo_excel):
    df=pd.read_excel(arquivo_excel);cols={_normalizar_coluna(c):c for c in df.columns};p=[]
    for x in ('numero_patente','data_deposito'):
        if _normalizar_coluna(x) not in cols:p.append(f'Coluna obrigatória não encontrada: {x}')
    if 'numero_patente' in cols:
        c=cols['numero_patente'];v=int(df[c].isna().sum());dups=df[df[c].duplicated(keep=False)][c].dropna().unique()
        if v:p.append(f'{v} linha(s) sem número de patente.')
        if len(dups):p.append('Números de patente duplicados: '+', '.join(map(str,dups)))
    return p

COLUNAS_PATENTES={'id':'ID','numero_patente':'Número da Patente','titulo':'Título','data_deposito':'Data de Depósito','data_concessao':'Data de Concessão','status':'Status','gestor':'Gestor','campus':'Campus','titular':'Titular','inventores':'Inventores','descricao':'Descrição','atributos':'Atributos'}
COLUNAS_ANUIDADES={'patente_id':'ID Patente','numero_patente':'Número da Patente','titulo':'Título','data_deposito':'Data de Depósito','data_concessao':'Data de Concessão','gestor':'Gestor','campus':'Campus','status_patente':'Status da Patente','numero_anuidade':'Anuidade','data_inicio_ordinario':'Início Ordinário','data_fim_ordinario':'Fim Ordinário','data_inicio_extraordinario':'Início Extraordinário','data_fim_extraordinario':'Fim Extraordinário','status_anuidade':'Status da Anuidade','data_pagamento':'Data de Pagamento','titular':'Titular','inventores':'Inventores','observacao':'Observação'}


def obter_dados_exportacao(tipo='Patentes',busca='',gestores=None,status_patentes=None,campi=None,status_anuidades=None):
    df=obter_patentes() if tipo=='Patentes' else obter_dataset_anuidades();gestores=gestores or [];status_patentes=status_patentes or [];campi=campi or [];status_anuidades=status_anuidades or []
    if busca:
        mask=pd.Series(False,index=df.index);t=str(busca).lower().strip()
        for c in df.columns:
            mask |= df[c].fillna('').astype(str).str.lower().str.contains(t,regex=False)
        df=df[mask]
    if gestores and 'gestor' in df:df=df[df.gestor.fillna('').isin(gestores)]
    if status_patentes:
        c='status_patente' if 'status_patente' in df else 'status';df=df[df[c].fillna('').isin(status_patentes)]
    if campi and 'campus' in df:df=df[df.campus.fillna('').isin(campi)]
    if status_anuidades and 'status_anuidade' in df:df=df[df.status_anuidade.fillna('').isin(status_anuidades)]
    return df.reset_index(drop=True)


def preparar_exportacao(df,colunas):
    out=df[[c for c in colunas if c in df.columns]].copy()
    for c in out.columns:
        if 'data_' in c:
            out[c]=pd.to_datetime(out[c],errors='coerce').dt.strftime('%d/%m/%Y').fillna('')
    mapa={**COLUNAS_PATENTES,**COLUNAS_ANUIDADES};return out.rename(columns={c:mapa.get(c,c) for c in out.columns})


def dataframe_para_excel(df,nome_aba='Patentes'):
    from io import BytesIO
    b=BytesIO()
    with pd.ExcelWriter(b,engine='openpyxl') as w:
        df.to_excel(w,index=False,sheet_name=nome_aba[:31]);ws=w.book[nome_aba[:31]];ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width=min(max(len(str(x.value or '')) for x in col)+2,60)
    b.seek(0);return b


def dataframe_para_csv(df):
    from io import BytesIO
    return BytesIO(df.to_csv(index=False,sep=';',encoding='utf-8-sig').encode('utf-8-sig'))


def exportar_para_excel(df): return dataframe_para_excel(df,'Patentes')
def exportar_para_csv(df): return dataframe_para_csv(df)
