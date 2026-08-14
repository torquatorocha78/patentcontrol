# database.py
import sqlite3
import pandas as pd
from datetime import date
import unicodedata

DB_NAME = "patentes.db"


def conectar():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


def init_database():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS patentes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero_patente TEXT UNIQUE,
        data_deposito DATE,
        data_concessao DATE,
        descricao TEXT,
        titular TEXT,
        gestor TEXT,
        status TEXT
    )
    """)

    colunas_existentes = {
        row[1] for row in cur.execute("PRAGMA table_info(patentes)").fetchall()
    }
    novas_colunas = {
        "titulo": "TEXT",
        "inventores": "TEXT",
        "campus": "TEXT",
        "atributos": "TEXT",
        "tipo": "TEXT",       # Patente, Software, Desenho Industrial
        "linguagem": "TEXT"   # Apenas para Software
    }
    for coluna, tipo_col in novas_colunas.items():
        if coluna not in colunas_existentes:
            cur.execute(f"ALTER TABLE patentes ADD COLUMN {coluna} {tipo_col}")
            if coluna == "tipo":
                cur.execute("UPDATE patentes SET tipo = 'Patente' WHERE tipo IS NULL")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS anuidades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patente_id INTEGER,
        numero_anuidade INTEGER,
        data_inicio_ordinario DATE,
        data_fim_ordinario DATE,
        data_inicio_extraordinario DATE,
        data_fim_extraordinario DATE,
        data_pagamento DATE,
        status TEXT,
        FOREIGN KEY (patente_id) REFERENCES patentes(id)
    )
    """)

    conn.commit()
    conn.close()
    garantir_anuidades_existentes()


def obter_patentes():
    conn = conectar()
    df = pd.read_sql("SELECT * FROM patentes ORDER BY id", conn)
    conn.close()
    return df


def _valor_limpo(valor):
    if pd.isna(valor):
        return None
    if isinstance(valor, str):
        valor = valor.strip()
        return valor or None
    return valor


def _normalizar_coluna(coluna):
    texto = str(coluna).strip().lower()
    texto = "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    for char in ["/", "\\", "-", ".", "(", ")", ":", ";"]:
        texto = texto.replace(char, " ")
    return "_".join(texto.split())


def _normalizar_status(status):
    status = _valor_limpo(status)
    if not status:
        return "Ativo"

    status_texto = str(status).strip()
    chave = _normalizar_coluna(status_texto)
    mapa = {
        "patente_concedida": "Patente Concedida",
        "patente_concedda": "Patente Concedida",
        "concedido": "Patente Concedida",
        "tramitando_normal": "Tramitando Normal",
        "infederimento": "Indeferimento",
        "indeferimento": "Indeferimento",
        "recurso_contra_indeferimento": "Recurso contra indeferimento",
        "pedido_de_exame": "Pedido de exame",
        "transferida_a_titularidade": "Transferida a titularidade",
    }
    return mapa.get(chave, status_texto)


def _parse_data(valor):
    # Trata datas vindas do Excel ou inputs
    valor = _valor_limpo(valor)
    if valor is None:
        return None
    if hasattr(valor, "date") and not isinstance(valor, str):
        return valor.date().isoformat()

    texto = str(valor).strip()
    if not texto:
        return None

    try:
        partes = texto.replace("-", "/").split("/")
        if len(partes) == 3 and all(p.isdigit() for p in partes):
            primeiro, segundo = int(partes[0]), int(partes[1])
            dayfirst = primeiro > 12 or segundo <= 12
            data = pd.to_datetime(texto, dayfirst=dayfirst, errors="raise")
        else:
            data = pd.to_datetime(texto, dayfirst=True, errors="raise")
        return data.date().isoformat()
    except Exception:
        return texto


def _calcular_datas_anuidade(data_dep, numero_anuidade, tipo='Patente'):
    inicio = pd.to_datetime(data_dep)

    if tipo == 'Software':
        # Software tem apenas uma taxa única (número 1) logo no início
        ini_ord = inicio
    elif tipo == 'Desenho Industrial':
        # Desenho Industrial: cobranças em quinquênios (0, 5, 10, 15, 20 anos)
        anos_deslocamento = 5 * (numero_anuidade - 1)
        ini_ord = inicio + pd.DateOffset(years=anos_deslocamento)
    else:
        # Patente normal: anuidades anuais convencionais
        ini_ord = inicio + pd.DateOffset(years=numero_anuidade - 1)

    fim_ord = ini_ord + pd.DateOffset(months=3)
    ini_ext = fim_ord
    fim_ext = ini_ext + pd.DateOffset(months=3)

    return ini_ord.date(), fim_ord.date(), ini_ext.date(), fim_ext.date()


def _garantir_anuidades_patente(cur, patente_id, data_dep, tipo='Patente'):
    if not data_dep:
        return
    if not tipo:
        tipo = 'Patente'

    cur.execute(
        "SELECT numero_anuidade FROM anuidades WHERE patente_id = ?",
        (patente_id,),
    )
    existentes = {row[0] for row in cur.fetchall()}

    # Define o limite de pagamentos/períodos dependendo do tipo do ativo
    if tipo == 'Software':
        limite_taxas = 1
    elif tipo == 'Desenho Industrial':
        limite_taxas = 5  # 5 quinquênios cobrindo 25 anos de validade máxima
    else:
        limite_taxas = 20  # 20 anos de patentes ordinárias

    for numero_anuidade in range(1, limite_taxas + 1):
        if numero_anuidade in existentes:
            continue

        ini_ord, fim_ord, ini_ext, fim_ext = _calcular_datas_anuidade(
            data_dep,
            numero_anuidade,
            tipo
        )
        cur.execute(
            """
            INSERT INTO anuidades
            (patente_id, numero_anuidade,
             data_inicio_ordinario, data_fim_ordinario,
             data_inicio_extraordinario, data_fim_extraordinario,
             status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patente_id,
                numero_anuidade,
                ini_ord,
                fim_ord,
                ini_ext,
                fim_ext,
                "pendente",
            ),
        )


def garantir_anuidades_existentes():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("SELECT id, data_deposito, tipo FROM patentes")
    patentes = cur.fetchall()

    for patente_id, data_dep, tipo in patentes:
        _garantir_anuidades_patente(cur, patente_id, data_dep, tipo or 'Patente')

    conn.commit()
    conn.close()


def adicionar_patente(
    numero,
    data_dep,
    data_conc,
    descricao,
    titular,
    gestor=None,
    status_patente='Ativo',
    titulo=None,
    inventores=None,
    campus=None,
    atributos=None,
    tipo='Patente',
    linguagem=None
):
    conn = conectar()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            INSERT INTO patentes
            (numero_patente, data_deposito, data_concessao, descricao, titular, gestor, status,
             titulo, inventores, campus, atributos, tipo, linguagem)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                numero,
                data_dep,
                data_conc,
                descricao,
                titular,
                gestor,
                _normalizar_status(status_patente),
                titulo,
                inventores,
                campus,
                atributos,
                tipo,
                linguagem
            ),
        )
        patente_id = cur.lastrowid

        # Gera taxas respectivas de forma isolada
        _garantir_anuidades_patente(cur, patente_id, data_dep, tipo)

        conn.commit()
        return True, "Ativo cadastrado com sucesso!"

    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def atualizar_patente(
    patente_id,
    numero,
    data_dep,
    data_conc,
    descricao,
    titular,
    gestor=None,
    status_patente="Ativo",
    titulo=None,
    inventores=None,
    campus=None,
    atributos=None,
    tipo="Patente",
    linguagem=None
):
    conn = conectar()
    cur = conn.cursor()
    try:
        # Busca tipo e data atuais antes da modificação
        cur.execute("SELECT tipo, data_deposito FROM patentes WHERE id = ?", (patente_id,))
        antigo = cur.fetchone()

        cur.execute(
            """
            UPDATE patentes
            SET numero_patente = ?, data_deposito = ?, data_concessao = ?,
                descricao = ?, titular = ?, gestor = ?, status = ?,
                titulo = ?, inventores = ?, campus = ?, atributos = ?,
                tipo = ?, linguagem = ?
            WHERE id = ?
            """,
            (
                numero,
                data_dep,
                data_conc,
                descricao,
                titular,
                gestor,
                _normalizar_status(status_patente),
                titulo,
                inventores,
                campus,
                atributos,
                tipo,
                linguagem,
                patente_id,
            ),
        )

        # Se houver alteração crítica (tipo de ativo ou data de depósito), recalculamos
        if antigo:
            antigo_tipo, antiga_data = antigo
            if antigo_tipo != tipo or antiga_data != data_dep:
                cur.execute("DELETE FROM anuidades WHERE patente_id = ?", (patente_id,))
                _garantir_anuidades_patente(cur, patente_id, data_dep, tipo)

        conn.commit()
        return True, "Ativo atualizado com sucesso!"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def salvar_patente_importada(dados):
    conn = conectar()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id FROM patentes WHERE numero_patente = ?",
            (dados["numero"],),
        )
        existente = cur.fetchone()
    finally:
        conn.close()

    if existente:
        ok, msg = atualizar_patente(existente[0], **dados)
        return ok, "Atualizada: " + msg if ok else msg

    ok, msg = adicionar_patente(**dados)
    return ok, "Importada: " + msg if ok else msg


def obter_anuidades(patente_id):
    patente_id = int(patente_id)
    conn = conectar()
    cur = conn.cursor()
    cur.execute(
        "SELECT data_deposito, tipo FROM patentes WHERE id = ?",
        (patente_id,),
    )
    patente = cur.fetchone()
    if patente:
        data_dep, tipo = patente
        _garantir_anuidades_patente(cur, patente_id, data_dep, tipo or 'Patente')
        conn.commit()

    df = pd.read_sql(
        "SELECT * FROM anuidades WHERE patente_id = ? ORDER BY numero_anuidade",
        conn,
        params=(patente_id,),
    )
    conn.close()

    hoje = date.today()

    def normalizar_status(row):
        if row.get("status"):
            s = str(row["status"]).lower()
            if s == "nao_pagar":
                return "nao_pagar"
            if row.get("data_pagamento"):
                return "pago"
        if row.get("data_fim_extraordinario"):
            try:
                if pd.to_datetime(row["data_fim_extraordinario"]).date() < hoje:
                    return "pago"
            except Exception:
                pass
        return "pendente"

    df["status"] = df.apply(normalizar_status, axis=1)
    return df


def atualizar_status_anuidade(patente_id, numero_anuidade, novo_status, data_pagamento=None):
    patente_id = int(patente_id)
    numero_anuidade = int(numero_anuidade)
    conn = conectar()
    cur = conn.cursor()

    novo_status = novo_status.lower()

    if novo_status == "pago":
        cur.execute(
            """
            UPDATE anuidades
            SET data_pagamento = ?, status = 'pago'
            WHERE patente_id = ? AND numero_anuidade = ?
            """,
            (data_pagamento, patente_id, numero_anuidade),
        )
    elif novo_status == "nao_pagar":
        cur.execute(
            """
            UPDATE anuidades
            SET data_pagamento = NULL, status = 'nao_pagar'
            WHERE patente_id = ? AND numero_anuidade = ?
            """,
            (patente_id, numero_anuidade),
        )
    else:
        cur.execute(
            """
            UPDATE anuidades
            SET status = ?
            WHERE patente_id = ? AND numero_anuidade = ?
            """,
            (novo_status, patente_id, numero_anuidade),
        )

    conn.commit()
    conn.close()


def deletar_patente(patente_id):
    patente_id = int(patente_id)
    conn = conectar()
    cur = conn.cursor()
    cur.execute("DELETE FROM anuidades WHERE patente_id = ?", (patente_id,))
    cur.execute("DELETE FROM patentes WHERE id = ?", (patente_id,))
    conn.commit()
    conn.close()


def importar_excel(arquivo_excel):
    resultados = []
    try:
        df = pd.read_excel(arquivo_excel)
        colunas = {_normalizar_coluna(col): col for col in df.columns}

        def campo(*nomes):
            for nome in nomes:
                coluna = colunas.get(_normalizar_coluna(nome))
                if coluna is not None:
                    return coluna
            return None

        mapa = {
            "numero": campo("numero_patente", "numero", "patente"),
            "data_dep": campo("data_deposito", "data deposito", "deposito"),
            "data_conc": campo("data_concessao", "concessao"),
            "titulo": campo("titulo"),
            "descricao": campo("resumo", "descricao"),
            "inventores": campo("inventores", "nome dos inventores"),
            "titular": campo("titular", "depositante"),
            "gestor": campo("gestor"),
            "status": campo("status", "situacao"),
            "campus": campo("campus"),
            "atributos": campo("atributos"),
            "tipo": campo("tipo", "tipo de ativo", "tipo_ativo"),
            "linguagem": campo("linguagem", "linguagem_programacao")
        }

        for _, row in df.iterrows():
            numero = _valor_limpo(row.get(mapa["numero"])) if mapa["numero"] else None
            data_dep = _parse_data(row.get(mapa["data_dep"])) if mapa["data_dep"] else None

            if not numero or not data_dep:
                resultados.append((numero or "SEM_NUMERO", False, "Número ou data de depósito ausente"))
                continue

            dados = {
                "numero": str(numero),
                "data_dep": data_dep,
                "data_conc": _parse_data(row.get(mapa["data_conc"])) if mapa["data_conc"] else None,
                "descricao": _valor_limpo(row.get(mapa["descricao"])) if mapa["descricao"] else None,
                "titular": _valor_limpo(row.get(mapa["titular"])) if mapa["titular"] else None,
                "gestor": _valor_limpo(row.get(mapa["gestor"])) if mapa["gestor"] else None,
                "status_patente": _normalizar_status(row.get(mapa["status"])) if mapa["status"] else "Ativo",
                "titulo": _valor_limpo(row.get(mapa["titulo"])) if mapa["titulo"] else None,
                "inventores": _valor_limpo(row.get(mapa["inventores"])) if mapa["inventores"] else None,
                "campus": _valor_limpo(row.get(mapa["campus"])) if mapa["campus"] else None,
                "atributos": _valor_limpo(row.get(mapa["atributos"])) if mapa["atributos"] else None,
                "tipo": _valor_limpo(row.get(mapa["tipo"])) or "Patente",
                "linguagem": _valor_limpo(row.get(mapa["linguagem"])) if mapa["linguagem"] else None,
            }
            ok, msg = salvar_patente_importada(dados)
            resultados.append((numero, ok, msg))
    except Exception as e:
        resultados.append(("ERRO_GERAL", False, str(e)))

    return resultados


def analisar_inconsistencias_excel(arquivo_excel):
    df = pd.read_excel(arquivo_excel)
    problemas = []

    colunas_originais = list(df.columns)
    colunas_normalizadas = {_normalizar_coluna(col): col for col in colunas_originais}

    obrigatorias = ["numero_patente", "data_deposito"]
    for obrigatoria in obrigatorias:
        if _normalizar_coluna(obrigatoria) not in colunas_normalizadas:
            problemas.append(f"Coluna obrigatória não encontrada: {obrigatoria}")

    return problemas
