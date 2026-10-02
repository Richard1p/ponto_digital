"""Controle de Horas 2.0: aplicação Flask local."""
from datetime import date
from pathlib import Path
import calendar
import json
import socket
import threading
import time
import webbrowser
from urllib.request import urlopen

from flask import Flask, abort, jsonify, make_response, redirect, render_template, request, url_for
from dados.banco import BancoHoras
from regras import calculo_horas as horas
from regras import financeiro

ROOT = Path(__file__).resolve().parent
app = Flask(__name__)
app.add_template_filter(financeiro.formatar_moeda, name="moeda")
db = BancoHoras(ROOT / "banco_horas.db")
DIAS = ("Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo")
TIPOS = (*DIAS, "Sábado Escala", "Segunda Feriado", "Terça Feriado", "Quarta Feriado", "Quinta Feriado", "Sexta Feriado", "Sábado Feriado", "Domingo Feriado")
PADRAO = {
    "jornada_util": "08:24", "jornada_sabado": "08:00", "tolerancia": "00:10",
    "limite_banco_util": "02:00", "limite_banco_sabado": "04:00", "divisor_mensal": "220",
    "multiplicador_banco_credito": "1.5", "multiplicador_banco_deficit": "1.0",
    "multiplicador_he50": "1.5", "multiplicador_he100": "2.0", "dsr_percentual": "0.20",
    "defasagem_he": "2", "defasagem_banco": "4", "salario_base": "0", "dependentes": "0",
    "previdencia_complementar": "0.00", "outros_descontos_base_ir": "0.00",
}
REGRAS_DURACAO = ("jornada_util", "jornada_sabado", "tolerancia", "limite_banco_util", "limite_banco_sabado")
REGRAS_NUMERICAS = ("divisor_mensal", "multiplicador_banco_credito", "multiplicador_banco_deficit", "multiplicador_he50", "multiplicador_he100", "dsr_percentual")


def config_atual():
    atual = PADRAO.copy()
    atual.update(db.buscar_configuracoes())
    return atual


def aplicar_config(config=None):
    config = config or config_atual()
    def minutos(chave):
        h, m = map(int, config[chave].split(":"))
        if h < 0 or not 0 <= m < 60:
            raise ValueError(f"Duração inválida: {chave}")
        return h * 60 + m
    horas.JORNADA_DIA_UTIL = horas.timedelta(minutes=minutos("jornada_util"))
    horas.JORNADA_SABADO_ESCALA = horas.timedelta(minutes=minutos("jornada_sabado"))
    horas.TOLERANCIA_PONTO = horas.timedelta(minutes=minutos("tolerancia"))
    horas.LIMITE_BANCO_DIA_UTIL = horas.timedelta(minutes=minutos("limite_banco_util"))
    horas.LIMITE_BANCO_SABADO = horas.timedelta(minutes=minutos("limite_banco_sabado"))
    financeiro.MULTIPLICADOR_BANCO_CREDITO = float(config["multiplicador_banco_credito"].replace(",", "."))
    financeiro.MULTIPLICADOR_BANCO_DEFICIT = float(config["multiplicador_banco_deficit"].replace(",", "."))
    financeiro.MULTIPLICADOR_HE50 = float(config["multiplicador_he50"].replace(",", "."))
    financeiro.MULTIPLICADOR_HE100 = float(config["multiplicador_he100"].replace(",", "."))
    financeiro.PERCENTUAL_DSR_PADRAO = float(config["dsr_percentual"].replace(",", "."))
    return config


aplicar_config()


def competencia():
    hoje = date.today()
    try:
        mes = int(request.values.get("mes", hoje.month))
        ano = int(request.values.get("ano", hoje.year))
    except (TypeError, ValueError):
        abort(400, "Mês ou ano inválido.")
    if not 1 <= mes <= 12 or not 2000 <= ano <= 2100:
        abort(400, "Mês ou ano inválido.")
    return mes, ano


def gerar_mes(mes, ano):
    import calendar
    for n in range(1, calendar.monthrange(ano, mes)[1] + 1):
        dia = date(ano, mes, n)
        texto = dia.strftime("%d/%m/%Y")
        if db.buscar_dia(texto) is None:
            db.salvar_linha_horas([texto, DIAS[dia.weekday()], "", "Sim", "", "", "", "", "", "", ""])


def formatar_minutos(minutos):
    sinal = "-" if minutos < 0 else ""
    minutos = abs(int(minutos))
    return f"{sinal}{minutos // 60:02d}:{minutos % 60:02d}"


def minutos_simulador(texto):
    texto = str(texto or "0").strip()
    if ":" in texto:
        partes = texto.split(":")
        if len(partes) != 2 or not all(p.isdigit() for p in partes) or int(partes[1]) > 59:
            raise ValueError("Use HH:MM para informar horas.")
        return int(partes[0]) * 60 + int(partes[1])
    if not texto.isdigit():
        raise ValueError("Informe um número de horas ou HH:MM.")
    return int(texto) * 60


def moeda_campo(valor):
    texto = str(valor or "0").strip().replace("R$", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    return float(texto)


def competencia_defasada(mes, ano, defasagem):
    indice = (ano * 12) + (mes - 1) - int(defasagem)
    ano_origem, mes_indice = divmod(indice, 12)
    return mes_indice + 1, ano_origem


def valores_horas_competencia(mes, ano, salario=None):
    config = config_atual()
    salario = moeda_campo(salario if salario is not None else config["salario_base"])
    divisor = float(config["divisor_mensal"].replace(",", "."))
    if divisor <= 0:
        divisor = 220
    banco_m, he50_m, he100_m = db.buscar_totais_mes(mes, ano)
    valor_hora = salario / divisor
    return (
        financeiro.valor_banco(banco_m, valor_hora),
        financeiro.valor_he50(he50_m, valor_hora),
        financeiro.valor_he100(he100_m, valor_hora),
    )


def valor_linha_em_reais(linha, salario, divisor):
    """Converte o saldo de banco e as horas extras de um dia em reais."""
    divisor = divisor if divisor > 0 else 220
    valor_hora = salario / divisor
    banco = horas.converter_string_para_minutos(linha[7] or "")
    he50 = horas.converter_string_para_minutos(linha[8] or "")
    he100 = horas.converter_string_para_minutos(linha[9] or "")
    return round(
        financeiro.valor_banco(banco, valor_hora)
        + financeiro.valor_he50(he50, valor_hora)
        + financeiro.valor_he100(he100, valor_hora),
        2,
    )


def dados_financeiros(mes, ano, salario=None, dependentes=None, deducoes=0):
    config = config_atual()
    salario = moeda_campo(salario if salario is not None else config["salario_base"])
    divisor = float(config["divisor_mensal"].replace(",", "."))
    if divisor <= 0:
        divisor = 220
    mes_he, ano_he = competencia_defasada(mes, ano, config.get("defasagem_he", "0"))
    mes_banco, ano_banco = competencia_defasada(mes, ano, config.get("defasagem_banco", "0"))
    banco_recebido_m = db.buscar_totais_mes(mes_banco, ano_banco)[0]
    banco_mes_pagamento = db.buscar_totais_mes(mes, ano)[0]
    # Déficits do mês do holerite reduzem o banco que está sendo pago. Quando
    # a defasagem é zero, o saldo já é o próprio mês e não pode ser subtraído
    # uma segunda vez.
    ajuste_deficit = (
        min(0, banco_mes_pagamento)
        if (mes_banco, ano_banco) != (mes, ano)
        else 0
    )
    banco_m = banco_recebido_m + ajuste_deficit
    _, he50_m, he100_m = db.buscar_totais_mes(mes_he, ano_he)
    valor_hora = salario / divisor
    v_banco = financeiro.valor_banco(banco_m, valor_hora)
    v_he50 = financeiro.valor_he50(he50_m, valor_hora)
    v_he100 = financeiro.valor_he100(he100_m, valor_hora)
    dsr = financeiro.valor_dsr_horas_extras(v_banco + v_he50 + v_he100)
    bruto = salario + v_banco + v_he50 + v_he100 + dsr
    dep = int(dependentes if dependentes is not None else config["dependentes"])
    valores_mensais = db.buscar_configuracao_folha_mensal(mes, ano)
    if valores_mensais is None:
        previdencia = moeda_campo(config.get("previdencia_complementar", "0"))
        outros_configurados = moeda_campo(config.get("outros_descontos_base_ir", "0"))
    else:
        previdencia, outros_configurados = map(float, valores_mensais)
    outros_base_ir = outros_configurados + float(deducoes or 0)
    calculo_folha = financeiro.calcular_folha_2026(
        bruto,
        previdencia_complementar=previdencia,
        outros_descontos_base_ir=outros_base_ir,
        dependentes=dep,
    )
    inss = calculo_folha.inss_retido
    irrf = calculo_folha.irrf_final
    descontos = sum(float(row[2] or 0) for row in db.buscar_descontos_mes(mes, ano))
    descontos_totais = inss + irrf + previdencia + descontos
    return {
        "salario": salario, "valor_hora": valor_hora, "banco_valor": v_banco,
        "he50_valor": v_he50, "he100_valor": v_he100, "dsr": dsr,
        "bruto": bruto, "inss": inss, "irrf": irrf, "descontos": descontos,
        "descontos_totais": descontos_totais,
        "previdencia_complementar": previdencia,
        "outros_descontos_base_ir": outros_base_ir,
        "base_ir_legal": calculo_folha.base_ir_legal,
        "base_ir": calculo_folha.base_ir,
        "deducao_simplificada": calculo_folha.deducao_simplificada,
        "metodo_deducao_ir": calculo_folha.metodo_deducao_ir,
        "imposto_padrao": calculo_folha.imposto_padrao,
        "valor_redutor_irrf": calculo_folha.valor_redutor,
        "deducao_dependentes": calculo_folha.deducao_dependentes,
        "liquido": bruto - descontos_totais,
        "totais": (banco_m, he50_m, he100_m),
        "dependentes": dep,
        "banco_recebido_minutos": banco_recebido_m,
        "ajuste_deficit_minutos": ajuste_deficit,
        "banco_liquido_minutos": banco_m,
        "competencia_he": (mes_he, ano_he), "competencia_banco": (mes_banco, ano_banco),
    }


def simular_horas(mes, ano, salario, he50, he100, banco):
    import holidays

    config = config_atual()
    salario = moeda_campo(salario)
    divisor = float(config["divisor_mensal"].replace(",", "."))
    if salario < 0 or divisor <= 0:
        raise ValueError("Salário ou divisor inválido.")
    m50, m100, minutos_banco = map(minutos_simulador, (he50, he100, banco))
    valor_hora = salario / divisor
    valor_50 = financeiro.valor_he50(m50, valor_hora)
    valor_100 = financeiro.valor_he100(m100, valor_hora)
    extras = valor_50 + valor_100
    feriados = holidays.Brazil(subdiv="SP", years=ano)
    dias_no_mes = calendar.monthrange(ano, mes)[1]
    repousos = sum(
        1 for n in range(1, dias_no_mes + 1)
        if date(ano, mes, n).weekday() == 6 or date(ano, mes, n) in feriados
    )
    dias_uteis = dias_no_mes - repousos
    dsr = extras / dias_uteis * repousos if dias_uteis > 0 else 0
    return {
        "he50_horas": formatar_minutos(m50), "he100_horas": formatar_minutos(m100),
        "banco_horas": formatar_minutos(minutos_banco), "he50_valor": valor_50,
        "he100_valor": valor_100, "banco_valor": financeiro.valor_banco(minutos_banco, valor_hora),
        "dias_uteis": dias_uteis, "repousos": repousos, "dsr": dsr,
        "total_extras": extras + dsr,
    }


@app.get("/")
def index():
    mes, ano = competencia()
    aba = request.args.get("aba", "apontamentos")
    if aba not in {"apontamentos", "financeiro", "calculadora", "regras"}:
        aba = "apontamentos"
    gerar_mes(mes, ano)
    linhas = db.buscar_mes(f"{mes:02d}", str(ano))
    totais = db.buscar_totais_mes(mes, ano)
    extras_liquidas = formatar_minutos(totais[1] + totais[2] - totais[0])
    descontos = db.buscar_descontos_mes(mes, ano)
    folha = db.buscar_conferencia_folha(mes, ano)
    config = config_atual()
    deducoes_mes = db.buscar_configuracao_folha_mensal(mes, ano)
    if deducoes_mes is None:
        deducoes_mes = (
            float(config.get("previdencia_complementar", "0")),
            float(config.get("outros_descontos_base_ir", "0")),
        )
    config["previdencia_complementar"] = f"{deducoes_mes[0]:.2f}"
    config["outros_descontos_base_ir"] = f"{deducoes_mes[1]:.2f}"
    salario_base = moeda_campo(config["salario_base"])
    divisor = float(config["divisor_mensal"].replace(",", "."))
    valores_por_data = {
        linha[0]: valor_linha_em_reais(linha, salario_base, divisor)
        for linha in linhas
    }
    financeiro_mes = dados_financeiros(mes, ano)
    valores_competencia = tuple(
        financeiro.formatar_moeda(valor)
        for valor in valores_horas_competencia(mes, ano, config["salario_base"])
    )
    simulacao = None
    if request.args.get("simular") == "1":
        try:
            simulacao = simular_horas(
                mes, ano, request.args.get("salario", "0"), request.args.get("he50", "0"),
                request.args.get("he100", "0"), request.args.get("banco", "0"),
            )
        except (ValueError, TypeError):
            abort(400, "Confira os valores informados na simulação.")
    mensagem = request.args.get("mensagem", "")
    hoje = date.today()
    anos = sorted(set(db.buscar_anos()) | set(range(hoje.year - 5, hoje.year + 6)))
    return render_template(
        "index.html", mes=mes, ano=ano, aba=aba, linhas=linhas, totais=totais,
        anos=anos, descontos=descontos, folha=folha, config=config,
        financeiro_mes=financeiro_mes, simulacao=simulacao, mensagem=mensagem,
        tipos=TIPOS, atestado=horas.esta_atestado, valores_competencia=valores_competencia,
        valores_por_data=valores_por_data, extras_liquidas=extras_liquidas,
    )


@app.get("/favicon.ico")
def favicon():
    return make_response("", 204)


@app.get("/health")
def health():
    return jsonify(aplicacao="controle-horas-2", diretorio=str(ROOT.resolve()), status="ok")


@app.post("/apontamentos/salvar")
def salvar_apontamentos():
    mes, ano = competencia()
    atualizados = []
    config_financeira = config_atual()
    salario_base = moeda_campo(config_financeira["salario_base"])
    divisor_mensal = float(config_financeira["divisor_mensal"].replace(",", "."))
    for iso in request.form.getlist("data"):
        try:
            dia = date.fromisoformat(iso)
        except ValueError:
            abort(400, "Data inválida.")
        if dia.month != mes or dia.year != ano:
            abort(400, "O apontamento não pertence à competência selecionada.")
        sufixo = iso
        tipo = request.form.get(f"tipo_{sufixo}", "").strip()
        if tipo not in TIPOS:
            abort(400, f"Tipo de dia inválido em {dia:%d/%m/%Y}.")
        observacao = request.form.get(f"obs_{sufixo}", "").strip()
        marcado = request.form.get(f"atestado_{sufixo}") == "on"
        obs = horas.aplicar_marcador_atestado(observacao, marcado)
        linha = [dia.strftime("%d/%m/%Y"), tipo, request.form.get(f"entrada_{sufixo}", ""),
                 "Sim" if request.form.get(f"almoco_{sufixo}") == "on" else "Não", "",
                 request.form.get(f"saida_{sufixo}", ""), "", "", "", "", obs]
        calculada = horas.calcular_linha(linha)
        db.salvar_linha_horas(calculada)
        atualizados.append({
            "data": iso, "prevista": calculada[6] or "—", "banco": calculada[7] or "—",
            "he50": calculada[8] or "—", "he100": calculada[9] or "—",
            "valor_dia": financeiro.formatar_moeda(
                valor_linha_em_reais(calculada, salario_base, divisor_mensal)
            ),
        })
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        totais = db.buscar_totais_mes(mes, ano)
        valores = valores_horas_competencia(mes, ano)
        saldo_extra_liquida = totais[1] + totais[2] - totais[0]
        return jsonify(
            ok=True, linhas=atualizados,
            totais=[formatar_minutos(valor) for valor in totais],
            extras_liquidas=formatar_minutos(saldo_extra_liquida),
            valores=[financeiro.formatar_moeda(valor) for valor in valores],
        )
    return redirect(url_for("index", mes=mes, ano=ano, aba="apontamentos", mensagem="Apontamentos salvos."))


@app.post("/financeiro/salvar")
def salvar_financeiro():
    mes, ano = competencia()
    try:
        salario = moeda_campo(request.form.get("salario"))
        dependentes = int(request.form.get("dependentes", "0"))
        previdencia = moeda_campo(request.form.get("previdencia_complementar", "0"))
        outros_base_ir = moeda_campo(request.form.get("outros_descontos_base_ir", "0"))
    except (ValueError, TypeError):
        abort(400, "Confira os valores de salário, dependentes e deduções.")
    if min(salario, dependentes, previdencia, outros_base_ir) < 0:
        abort(400, "Salário, dependentes e deduções não podem ser negativos.")
    db.salvar_configuracoes({"salario_base": f"{salario:.2f}", "dependentes": str(dependentes)})
    db.salvar_configuracao_folha_mensal(mes, ano, previdencia, outros_base_ir)
    return redirect(url_for("index", mes=mes, ano=ano, aba="financeiro", mensagem="Dados financeiros salvos."))


@app.post("/descontos/adicionar")
def adicionar_desconto():
    mes, ano = competencia()
    nome = request.form.get("nome", "").strip()
    valor = moeda_campo(request.form.get("valor"))
    if not nome or valor < 0:
        abort(400, "Informe uma descrição e um valor de desconto válido.")
    db.adicionar_desconto(nome, valor, mes, ano)
    return redirect(url_for("index", mes=mes, ano=ano, aba="financeiro", mensagem="Desconto incluído."))


@app.post("/descontos/remover/<int:identificador>")
def remover_desconto(identificador):
    mes, ano = competencia()
    db.remover_desconto(identificador)
    return redirect(url_for("index", mes=mes, ano=ano, aba="financeiro", mensagem="Desconto removido."))


@app.post("/folha/salvar")
def salvar_folha():
    mes, ano = competencia()
    try:
        campos = [
            moeda_campo(valor) if valor.strip() else None
            for valor in (request.form.get(k, "") for k in ("proventos_variaveis", "dsr", "inss", "irrf"))
        ]
    except (ValueError, TypeError):
        abort(400, "Confira os valores informados na conferência do holerite.")
    if any(valor is not None and valor < 0 for valor in campos):
        abort(400, "Os valores recebidos na conferência não podem ser negativos.")
    db.salvar_conferencia_folha(mes, ano, *campos)
    return redirect(url_for("index", mes=mes, ano=ano, aba="financeiro", mensagem="Conferência da folha salva."))


@app.post("/regras/salvar")
def salvar_regras():
    mes, ano = competencia()
    novo = {key: request.form.get(key, "").strip() for key in (*REGRAS_DURACAO, *REGRAS_NUMERICAS, "defasagem_he", "defasagem_banco")}
    try:
        for key in REGRAS_DURACAO:
            h, m = map(int, novo[key].split(":"))
            if h < 0 or not 0 <= m < 60:
                raise ValueError
        for key in REGRAS_NUMERICAS:
            novo[key] = novo[key].replace(",", ".")
            numero = float(novo[key])
            if numero < 0 or (key == "divisor_mensal" and numero == 0):
                raise ValueError
        for key in ("defasagem_he", "defasagem_banco"):
            novo[key] = str(int(novo[key]))
            if int(novo[key]) < 0:
                raise ValueError
        candidatos = config_atual()
        candidatos.update(novo)
        aplicar_config(candidatos)
    except (ValueError, TypeError, KeyError):
        abort(400, "Revise as durações HH:MM e os valores numéricos das regras.")
    db.salvar_configuracoes(novo)
    for linha in db.buscar_todos_lancamentos():
        db.salvar_linha_horas(horas.calcular_linha(list(linha)))
    return redirect(url_for("index", mes=mes, ano=ano, aba="regras", mensagem="Regras salvas e aplicadas aos apontamentos."))


def selecionar_porta():
    """Prefere a porta padrão e usa a próxima livre quando ela já está ocupada."""
    for porta in range(5000, 5011):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as teste:
            try:
                teste.bind(("127.0.0.1", porta))
                return porta
            except OSError:
                continue
    raise RuntimeError("Não encontrei uma porta livre entre 5000 e 5010.")


def instancia_existente():
    """Retorna a porta desta aplicação se ela já estiver rodando localmente."""
    for porta in range(5000, 5011):
        try:
            with urlopen(f"http://127.0.0.1:{porta}/health", timeout=0.2) as resposta:
                dados = json.loads(resposta.read().decode("utf-8"))
            if (dados.get("aplicacao") == "controle-horas-2"
                    and dados.get("diretorio") == str(ROOT.resolve())):
                return porta
        except (OSError, ValueError):
            continue
    return None


def abrir_navegador(porta):
    url = f"http://127.0.0.1:{porta}"
    limite = time.monotonic() + 12
    while time.monotonic() < limite:
        try:
            with socket.create_connection(("127.0.0.1", porta), timeout=0.5):
                webbrowser.open_new(url)
                return
        except OSError:
            time.sleep(0.2)


def main():
    existente = instancia_existente()
    if existente is not None:
        webbrowser.open_new_tab(f"http://127.0.0.1:{existente}")
        return
    porta = selecionar_porta()
    threading.Thread(target=abrir_navegador, args=(porta,), daemon=True).start()
    print(f"Controle de Horas disponível em http://127.0.0.1:{porta}")
    app.run(host="127.0.0.1", port=porta, debug=False, use_reloader=False, threaded=False)


if __name__ == "__main__":
    main()
