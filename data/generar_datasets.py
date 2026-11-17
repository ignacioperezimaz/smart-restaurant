"""Generador de datos sintéticos de restauración · proyecto smart-restaurant.

Genera CUATRO fuentes en DOS lotes (histórico y lote_drift) y después las ENSUCIA
de forma controlada y reproducible. Las fuentes están diseñadas para los objetivos del ML:

  Objetivo 1 (regresión): predecir los clientes diarios del restaurante
      <- encadenado con (clasificación): ¿asistirá o no una reserva?
         fuentes: reservas (una fila por reserva) + afluencia_diaria
  Objetivo 2 (clustering): agrupar platos por popularidad, precio, coste y margen
      <- encadenado con (clasificación): sentimiento de las reseñas
         fuentes: rendimiento_platos + resenas (comentario en texto)

Uso:  python generar_datasets.py [directorio_de_salida]      (requiere numpy)
Todo es reproducible: la semilla es fija (SEED).
"""
import csv, json, math, sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import numpy as np

# ----------------------------------------------------------------------------
# PARÁMETROS GENERALES (se pueden ajustar para cambiar el tamaño de los datos)
# ----------------------------------------------------------------------------
SEED = 20261117
N_RESTAURANTES = 24        # restaurantes ficticios (3 por ciudad)
N_CLIENTES = 9000          # pool de clientes seudonimizados (sin datos personales)
PLATOS_POR_CLIENTE = 2.2   # platos medios que pide cada cliente
MEDIA_GRUPO = 3.23         # tamaño medio de una reserva (según SIZES/PS)

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
OUT.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(SEED)       # generador de los datos limpios
err = np.random.default_rng(SEED + 1)   # generador independiente del ensuciado

# (inicio, fin, ¿es el lote con drift?)
PERIODOS = {
    'historico': (date(2024, 1, 1), date(2025, 12, 31), False),
    'lote_drift': (date(2026, 1, 1), date(2026, 6, 30), True),
}

# Parámetros que cambian entre el histórico y el lote drift (data drift y concept drift)
PARAMS = {
    False: dict(temp_extra=0.0, p_lluvia=.28, p_web=.53, b0=-3.60, b_antel=.045, b_web=.35,
                precio=1.0, coste=1.0, resena_shift=0.0, p_precio_neg=.10),
    True:  dict(temp_extra=0.9, p_lluvia=.37, p_web=.70, b0=-4.10, b_antel=.060, b_web=.55,
                precio=1.035, coste=1.12, resena_shift=-.30, p_precio_neg=.35),
}

# ----------------------------------------------------------------------------
# CATÁLOGO DE PLATOS: nombre, categoría, precio base, coste base, popularidad,
# calidad percibida (0-1, influye en las reseñas) y amplitud estacional (+verano / -invierno)
# Los precios/costes/popularidades están pensados para que existan grupos claros:
# platos caros y poco pedidos, populares de precio medio, entrantes baratos de alto margen, etc.
# ----------------------------------------------------------------------------
DISHES = [
    ('Hamburguesa clásica', 'Principal', 13.5, 5.4, 1.25, .72, 0.0),
    ('Pizza margarita', 'Principal', 12.5, 4.5, 1.15, .74, 0.0),
    ('Pasta boloñesa', 'Principal', 14.5, 5.8, 1.00, .70, 0.0),
    ('Solomillo a la plancha', 'Principal', 24.5, 14.8, .42, .80, 0.0),
    ('Salmón al horno', 'Principal', 19.0, 10.9, .50, .75, 0.0),
    ('Arroz de verduras', 'Principal', 13.0, 4.0, .70, .68, .10),
    ('Merluza a la vasca', 'Principal', 20.5, 8.6, .62, .82, 0.0),
    ('Bacalao al pil-pil', 'Principal', 21.0, 8.4, .58, .85, -.10),
    ('Chuletón para compartir', 'Principal', 38.0, 24.0, .25, .90, 0.0),
    ('Croquetas caseras', 'Entrante', 8.5, 2.2, 1.40, .88, 0.0),
    ('Patatas bravas', 'Entrante', 7.0, 1.8, 1.30, .80, 0.0),
    ('Ensalada de temporada', 'Entrante', 9.5, 2.9, .80, .66, .30),
    ('Sopa del día', 'Entrante', 7.5, 3.3, .40, .58, -.45),
    ('Pimientos de Gernika', 'Entrante', 8.0, 2.4, .95, .78, .10),
    ('Ensaladilla rusa', 'Entrante', 7.5, 2.0, 1.00, .76, .20),
    ('Tarta de queso', 'Postre', 6.5, 1.5, 1.20, .90, 0.0),
    ('Brownie de chocolate', 'Postre', 6.0, 1.7, .70, .72, 0.0),
    ('Goxua', 'Postre', 6.0, 1.6, .65, .84, 0.0),
    ('Flan casero', 'Postre', 4.5, 1.3, .55, .62, 0.0),
    ('Helado artesano', 'Postre', 5.0, 1.9, .60, .70, .45),
]
N_PLATOS = len(DISHES)
D_PRECIO = np.array([d[2] for d in DISHES]); D_COSTE = np.array([d[3] for d in DISHES])
D_POP = np.array([d[4] for d in DISHES]);    D_CALIDAD = np.array([d[5] for d in DISHES])
D_AMP = np.array([d[6] for d in DISHES])

CITIES = [('Donostia', 'Gipuzkoa'), ('Bilbao', 'Bizkaia'), ('Vitoria-Gasteiz', 'Araba'),
          ('Pamplona', 'Navarra'), ('Santander', 'Cantabria'), ('Logroño', 'La Rioja'),
          ('Burgos', 'Burgos'), ('Oviedo', 'Asturias')]
TIPOS = ['casual', 'bistró', 'familiar', 'tradicional']
DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
WD = [.78, .83, .90, 1.0, 1.28, 1.43, 1.14]          # demanda según día de la semana (lunes=0)
FESTIVOS = {(1, 1), (1, 6), (5, 1), (8, 15), (10, 12), (11, 1), (12, 6), (12, 8), (12, 25)}

# Reservas: tamaño del grupo, horas de reserva y plataformas de reseñas
SIZES = np.array([1, 2, 3, 4, 5, 6, 7, 8]); PS = np.array([.07, .40, .14, .21, .07, .05, .03, .03])
HORAS = {'comida': (['13:00', '13:30', '14:00', '14:30', '15:00'], [.15, .30, .30, .15, .10]),
         'cena': (['20:30', '21:00', '21:30', '22:00'], [.20, .35, .30, .15])}
PLATAFORMAS = (['Google', 'TripAdvisor', 'TheFork'], [.55, .25, .20])

# ----------------------------------------------------------------------------
# TEXTO DE LAS RESEÑAS (frases propias). {plato} se sustituye por el plato mencionado.
# ----------------------------------------------------------------------------
PLATO_FRASES = {
    'pos': ['Pedimos {plato} y estaba buenísimo.', 'Lo mejor de la comida fue {plato}, de diez.',
            '{plato} estaba espectacular, repetiremos.', 'Destaco {plato}: sabor casero y ración generosa.',
            'Probamos {plato} y fue todo un acierto.'],
    'neu': ['{plato} estaba correcto, sin más.', 'Probamos {plato}: está bien, pero esperaba algo más.',
            'El plato {plato} normalito, ni bueno ni malo.', '{plato} cumple, aunque nada del otro mundo.'],
    'neg': ['{plato} llegó frío y sin sabor.', 'Pedimos {plato} y fue una decepción.',
            '{plato} estaba pasado y mal presentado.', 'No recomiendo {plato}, muy flojo.'],
}
GENERAL_FRASES = {
    'pos': ['El servicio fue excelente y muy atento.', 'Ambiente agradable y buena relación calidad-precio.',
            'Muy recomendable, volveremos seguro.', 'Atención de primera y comida de calidad.',
            'Salimos encantados con la experiencia.'],
    'neu': ['El servicio fue normal y el local correcto.', 'Está bien por lo que cuesta, nada especial.',
            'Una experiencia aceptable, sin sorpresas.', 'Cumple, aunque no repetiría necesariamente.'],
    'neg': ['El servicio fue lento y poco amable.', 'Salimos bastante decepcionados.',
            'No volveremos, la experiencia fue mala.', 'Poca atención y comida mejorable.'],
}
ESPERA_FRASES = ['Tardaron muchísimo en servirnos, el local estaba lleno.', 'Esperamos más de una hora por la comida.',
                 'Estaba todo saturado y nos atendieron fatal.', 'Mucho retraso y camareros desbordados.']
PRECIO_FRASES = ['Los precios están por las nubes para lo que ofrecen.', 'Demasiado caro para la ración que sirven.',
                 'Han subido los precios y ya no compensa.', 'Cuenta excesiva, mala relación calidad-precio.']

# ----------------------------------------------------------------------------
# COLUMNAS Y REGLAS DE ENSUCIADO
# ----------------------------------------------------------------------------
FIELDS = {
    'afluencia_diaria': ['id_registro', 'id_restaurante', 'fecha_servicio', 'ciudad', 'provincia', 'tipo_restaurante',
                         'capacidad_asientos', 'dia_semana', 'mes', 'temporada', 'festivo_simulado', 'evento_local_previsto',
                         'temperatura_prevista_c', 'lluvia_prevista_mm', 'horas_apertura_planificadas',
                         'fecha_corte_prediccion', 'clientes_reales', 'clientes_con_reserva_reales', 'clientes_sin_reserva_reales'],
    'reservas': ['id_registro', 'id_restaurante', 'fecha_servicio', 'turno', 'hora_reserva', 'comensales', 'antelacion_dias',
                 'canal', 'id_cliente', 'reservas_previas_cliente', 'cancelaciones_previas_cliente',
                 'no_shows_previos_cliente', 'estado_final'],
    'rendimiento_platos': ['id_registro', 'id_restaurante', 'fecha_servicio', 'id_plato', 'nombre_plato', 'categoria', 'ofertado',
                           'precio_unitario_eur', 'coste_unitario_eur', 'unidades_vendidas', 'descuento_medio_pct',
                           'ventas_netas_eur', 'coste_total_eur', 'margen_contribucion_eur'],
    'resenas': ['id_registro', 'id_restaurante', 'fecha_visita', 'fecha_resena', 'plataforma', 'id_plato', 'puntuacion', 'comentario'],
}
FUENTES_INFO = {
    'afluencia_diaria': ('Clientes reales por restaurante y día (con y sin reserva), con clima previsto y calendario', 'restaurante + día'),
    'reservas': ('Una fila por reserva: antelación, grupo, canal, historial del cliente y resultado final', 'una reserva'),
    'rendimiento_platos': ('Ventas, coste y margen por restaurante, día y plato', 'restaurante + día + plato'),
    'resenas': ('Reseñas de clientes (plataforma, puntuación y comentario en texto) asociadas a un plato', 'una reseña'),
}
# Cada anomalía afecta como máximo a una columna de una fila limpia elegida al azar (tipos disjuntos).
RULES = {
    'afluencia_diaria': {
        'nulos': ['clientes_reales', 'temperatura_prevista_c', 'capacidad_asientos', 'ciudad', 'horas_apertura_planificadas'],
        'tipos': {'clientes_reales': 'muchos', 'capacidad_asientos': 'sesenta', 'lluvia_prevista_mm': 'lluvia', 'festivo_simulado': 'desconocido'},
        'incorrectos': {'clientes_reales': -18, 'capacidad_asientos': 0, 'mes': 14, 'horas_apertura_planificadas': 29, 'dia_semana': 'Funday'},
        'outliers': {'clientes_reales': 9500, 'temperatura_prevista_c': 78.1, 'lluvia_prevista_mm': 900},
        'formatos': ['fecha_servicio', 'fecha_corte_prediccion', 'temperatura_prevista_c', 'ciudad'],
        'categorias': {'tipo_restaurante': 0, 'temporada': 0}},
    'reservas': {
        'nulos': ['turno', 'hora_reserva', 'comensales', 'antelacion_dias', 'canal', 'id_cliente', 'estado_final'],
        'tipos': {'comensales': 'cuatro', 'antelacion_dias': 'una semana', 'cancelaciones_previas_cliente': 'varias'},
        'incorrectos': {'comensales': -3, 'antelacion_dias': -5, 'hora_reserva': '27:90', 'estado_final': 'quizás'},
        'outliers': {'comensales': 250, 'antelacion_dias': 900, 'reservas_previas_cliente': 5000},
        'formatos': ['fecha_servicio', 'hora_reserva', 'comensales', 'turno'],
        'categorias': {'canal': 0, 'estado_final': 0, 'turno': 0}},
    'rendimiento_platos': {
        'nulos': ['id_plato', 'precio_unitario_eur', 'coste_unitario_eur', 'unidades_vendidas', 'categoria', 'nombre_plato'],
        'tipos': {'precio_unitario_eur': 'gratis?', 'coste_unitario_eur': 'pendiente', 'unidades_vendidas': 'muchas', 'ofertado': 'quizá'},
        'incorrectos': {'precio_unitario_eur': -8.5, 'coste_unitario_eur': -3, 'unidades_vendidas': -20, 'descuento_medio_pct': 145, 'coste_total_eur': -28},
        'outliers': {'precio_unitario_eur': 1800, 'unidades_vendidas': 12000, 'coste_unitario_eur': 950},
        'formatos': ['fecha_servicio', 'precio_unitario_eur', 'coste_unitario_eur', 'nombre_plato'],
        'categorias': {'categoria': 0, 'nombre_plato': 0}},
    'resenas': {
        'nulos': ['comentario', 'puntuacion', 'plataforma', 'id_plato', 'fecha_resena'],
        'tipos': {'puntuacion': 'cinco', 'puntuacion_alt': 'excelente'},
        'incorrectos': {'puntuacion': 0, 'puntuacion_alt': -1, 'puntuacion_alt2': 11},
        'outliers': {'puntuacion': 55},
        'formatos': ['fecha_visita', 'fecha_resena', 'comentario', 'plataforma'],
        'categorias': {'plataforma': 0}},
}
# Probabilidad acumulada de cada anomalía (por fila): 8,5 % con error de campo + 2 % duplicadas
LIMITS = [(.025, 'nulos'), (.040, 'tipos'), (.055, 'incorrectos'), (.070, 'formatos'),
          (.075, 'outliers'), (.080, 'categorias'), (.085, 'clave_huerfana'), (.105, 'duplicado')]
DEF_ERRORES = {
    'nulos': "Un campo vacío o con los marcadores '', 'NA', 'NULL' o 'sin dato'.",
    'tipos': 'Texto no numérico en una columna numérica (p. ej. "muchos", "sesenta", "cinco").',
    'incorrectos': 'Valor imposible (negativos, mes 14, 29 horas de apertura, día "Funday", hora 27:90, puntuación 11…).',
    'outliers': 'Valor numérico extremo, fuera de todo rango razonable (p. ej. 9500 clientes o puntuación 55).',
    'formatos': 'Formato distinto al estándar: fechas dd/mm/yyyy, yyyy/mm/dd, dd-mm-yyyy o la fecha imposible 31/02/2025; decimales con coma; símbolo €; horas "21.00 h"; texto en mayúsculas con espacios.',
    'clave_huerfana': "id_restaurante sustituido por 'RST-9999', que no existe como restaurante real.",
    'categorias': 'Categoría con espacios sobrantes y en mayúsculas (p. ej. "  BISTRÓ  ").',
    'duplicado': 'Fila idéntica repetida justo a continuación (mismo id_registro).',
}
NOTAS = {'escala_thefork': "Error SISTEMÁTICO (no aleatorio) en resenas: TheFork puntúa de 2 a 10 (el doble) y las demás plataformas de 1 a 5. Hay que reescalar."}


def rnd_choice(seq):
    return seq[int(err.integers(len(seq)))]


def corrupt(source, row):
    """Aplica como máximo un error a una fila limpia. Devuelve (fila, tipo_de_error | None)."""
    x = err.random()
    kind = next((k for lim, k in LIMITS if x < lim), None)
    if kind is None or kind == 'duplicado':
        return row, kind
    row = row.copy(); rules = RULES[source]
    if kind == 'clave_huerfana':
        row['id_restaurante'] = 'RST-9999'; return row, kind
    if kind == 'nulos':
        row[rnd_choice(rules[kind])] = rnd_choice(['', 'NA', 'NULL', 'sin dato']); return row, kind
    if kind in ('tipos', 'incorrectos', 'outliers'):
        col = rnd_choice(list(rules[kind])); row[col.split('_alt')[0]] = rules[kind][col]; return row, kind
    if kind == 'categorias':
        col = rnd_choice(list(rules[kind])); row[col] = '  ' + str(row[col]).upper() + '  '; return row, kind
    col = rnd_choice(rules['formatos']); val = row[col]          # kind == 'formatos'
    if col in ('fecha_servicio', 'fecha_visita', 'fecha_resena'):
        y, m, d = val.split('-')
        row[col] = rnd_choice([f'{d}/{m}/{y}', f'{y}/{m}/{d}', f'{d}-{m}-{y}', '31/02/2025'])
    elif col == 'fecha_corte_prediccion':
        row[col] = val.replace('T', ' ').replace('-', '/')
    elif col == 'hora_reserva':
        row[col] = val.replace(':', '.') + ' h'
    elif isinstance(val, (int, float)):
        row[col] = str(val).replace('.', ',') + (' €' if 'eur' in col else '')
    else:
        row[col] = '  ' + str(val).upper() + '  '
    return row, kind


# ----------------------------------------------------------------------------
# ENTIDADES: restaurantes y clientes
# ----------------------------------------------------------------------------
restaurantes = []
for i in range(N_RESTAURANTES):
    city, prov = CITIES[i % len(CITIES)]
    restaurantes.append(dict(
        id=f'RST-{i + 1:04d}', ciudad=city, prov=prov, tipo=TIPOS[i % 4], cap=int(rng.integers(35, 111)),
        precio_f=float(rng.uniform(.85, 1.18)),             # factor de precios del restaurante
        pop=float(rng.uniform(.85, 1.15)),                  # popularidad general
        q=float(rng.normal(0, .3)),                         # calidad propia del restaurante (afecta a las reseñas)
        prefs=rng.uniform(.75, 1.25, N_PLATOS),             # preferencias por platos
        x=0.0, idx=i))                                      # x: tendencia lenta (autocorrelación diaria)

lat_cli = rng.normal(0, 1, N_CLIENTES)                      # propensión oculta de cada cliente a fallar la reserva
hist_res = np.zeros(N_CLIENTES, dtype=int); hist_can = np.zeros(N_CLIENTES, dtype=int); hist_ns = np.zeros(N_CLIENTES, dtype=int)


def comentario(rating, plato, ocup, drift):
    """Genera el comentario de una reseña según su puntuación (con algo de ruido)."""
    s = 'pos' if rating >= 4 else 'neu' if rating == 3 else 'neg'
    gen = s
    if rng.random() < .07:                                  # 7 %: la frase general es del sentimiento vecino
        gen = {'pos': 'neu', 'neu': rnd_pool(['pos', 'neg']), 'neg': 'neu'}[s]
    frases = [rnd_list(PLATO_FRASES[s]).format(plato=plato)]
    if s == 'neg' and ocup > .85 and rng.random() < .6:
        frases.append(rnd_list(ESPERA_FRASES))
    elif s == 'neg' and rng.random() < PARAMS[drift]['p_precio_neg']:
        frases.append(rnd_list(PRECIO_FRASES))
    else:
        frases.append(rnd_list(GENERAL_FRASES[gen]))
    if rng.random() < .5:
        frases.reverse()
    return ' '.join(frases)


def rnd_list(seq):
    return seq[int(rng.integers(len(seq)))]


def rnd_pool(seq):
    return seq[int(rng.integers(len(seq)))]


def gen_periodo(nombre, d0, d1, drift):
    P = PARAMS[drift]
    files = {s: (OUT / f'{s}_{nombre}.csv').open('w', encoding='utf-8', newline='') for s in FIELDS}
    writers = {s: csv.DictWriter(files[s], fieldnames=FIELDS[s]) for s in FIELDS}
    counts = {s: Counter() for s in FIELDS}
    for w in writers.values():
        w.writeheader()
    fechas = {s: [None, None] for s in FIELDS}

    def emit(s, row):
        counts[s]['filas_originales'] += 1
        row, kind = corrupt(s, row)
        writers[s].writerow(row)
        if kind:
            counts[s][kind] += 1
        if kind == 'duplicado':
            writers[s].writerow(row)
        counts[s]['filas_csv'] += 1 + int(kind == 'duplicado')

    d = d0
    while d <= d1:
        dt = d.isoformat(); compact = dt.replace('-', ''); corte = (d - timedelta(days=1)).isoformat() + 'T23:59:00'
        wd = d.weekday(); month = d.month; yday = d.timetuple().tm_yday
        season = ['invierno', 'primavera', 'verano', 'otoño'][((month % 12) // 3)]
        holiday = int((month, d.day) in FESTIVOS)
        seasonal = math.sin(2 * math.pi * (yday - 85) / 365.25)      # +1 en verano, -1 en invierno
        infl_p = 1.04 if d.year >= 2025 else 1.0                      # inflación de precios
        infl_c = 1.055 if d.year >= 2025 else 1.0                     # inflación de costes
        for rest in restaurantes:
            rid = rest['id']
            # --- clima y calendario del día --------------------------------------------------
            temp = round(14 + 7.5 * seasonal + float(rng.normal(0, 2.5)) + P['temp_extra'], 1)
            lluvia = round(float(rng.gamma(1.5, 3.0)), 1) if rng.random() < P['p_lluvia'] else 0.0
            evento = int(rng.random() < .045)
            rest['x'] = .97 * rest['x'] + float(rng.normal(0, .03))   # tendencia lenta -> el historial es informativo
            f_cal = WD[wd] * (1 + .17 * holiday) * (1 + .24 * evento) * (.88 + .12 * seasonal)
            f_base = rest['cap'] * rest['pop'] * math.exp(rest['x']) * f_cal
            if drift:
                f_base *= .87 if rest['idx'] % 3 == 0 else 1.08
            share_res = .70 if wd >= 4 else .60                       # el fin de semana se reserva más
            d_res = f_base * share_res * (1 - .004 * min(lluvia, 20))
            d_walk = f_base * (1 - share_res) * math.exp(-.045 * min(lluvia, 15)) * (1 + .015 * (min(temp, 28) - 14))

            # --- RESERVAS (una fila por reserva) ---------------------------------------------
            con_reserva = 0; k = 0
            for turno, w in (('comida', .45), ('cena', .55)):
                n = int(rng.poisson(max(.01, d_res * w / MEDIA_GRUPO)))
                if n == 0:
                    continue
                size = rng.choice(SIZES, n, p=PS)
                mismo_dia = rng.random(n) < .18                                   # reservas hechas el mismo día
                antel = np.where(mismo_dia, 0, 1 + (rng.gamma(1.6, 4.0, n) * (1 + .12 * (size - 2)) * (1.25 if wd >= 4 else 1)).astype(int))
                antel = np.minimum(antel, 45)
                web = rng.random(n) < np.clip(P['p_web'] - .04 * (size - 2), .1, .95)
                hora = rng.choice(HORAS[turno][0], n, p=HORAS[turno][1])
                cli = rng.integers(0, N_CLIENTES, n)
                rp, cp, npv = hist_res[cli].copy(), hist_can[cli].copy(), hist_ns[cli].copy()   # historial ANTES de esta reserva
                z = (P['b0'] + P['b_antel'] * np.minimum(antel, 30) + .16 * np.clip(size - 3, -1, 5) + .30 * (wd in (4, 5))
                     + .20 * (turno == 'cena') + .035 * min(lluvia, 20) + P['b_web'] * web
                     + .45 * np.minimum(cp, 4) + .35 * np.minimum(npv, 3) + .55 * lat_cli[cli])
                falla = rng.random(n) < 1 / (1 + np.exp(-z))                      # ¿cancela o no se presenta?
                cancela = rng.random(n) < .62
                estado = np.where(falla, np.where(cancela, 'cancelada', 'no_show'), 'asistio')
                np.add.at(hist_res, cli, 1)
                np.add.at(hist_can, cli[estado == 'cancelada'], 1)
                np.add.at(hist_ns, cli[estado == 'no_show'], 1)
                con_reserva += int(size[estado == 'asistio'].sum())
                for j in range(n):
                    k += 1
                    emit('reservas', dict(zip(FIELDS['reservas'], [
                        f'RSV-{rid}-{compact}-{k:03d}', rid, dt, turno, str(hora[j]), int(size[j]), int(antel[j]),
                        'web' if web[j] else 'telefono', f'CLI-{int(cli[j]) + 1:05d}', int(rp[j]), int(cp[j]), int(npv[j]), str(estado[j])])))

            # --- AFLUENCIA DIARIA ------------------------------------------------------------
            sin_reserva = int(rng.poisson(max(.01, d_walk)))
            clientes = con_reserva + sin_reserva
            t_prev = round(temp + float(rng.normal(0, 1.2)), 1)
            l_prev = round(max(0.0, lluvia + float(rng.normal(0, 1.5))), 1)
            emit('afluencia_diaria', dict(zip(FIELDS['afluencia_diaria'], [
                f'AFL-{rid}-{compact}', rid, dt, rest['ciudad'], rest['prov'], rest['tipo'], rest['cap'], DIAS[wd], month, season,
                holiday, evento, t_prev, l_prev, 10 if wd in (4, 5) else 8, corte, clientes, con_reserva, sin_reserva])))

            # --- RENDIMIENTO DE PLATOS -------------------------------------------------------
            share = D_POP * rest['prefs'] * np.clip(1 + D_AMP * seasonal, .1, None)
            if drift:
                share = share * np.where(np.isin(np.arange(N_PLATOS), (5, 11)), 1.20, 1.0) * np.where(np.arange(N_PLATOS) == 8, .8, 1.0)
            share = share / share.sum()
            desc = rng.choice([0, 0, 0, 0, 5, 10, 15], N_PLATOS)
            ofertado = rng.random(N_PLATOS) > .015
            units = rng.poisson(clientes * PLATOS_POR_CLIENTE * share * (1 + .010 * desc)) * ofertado
            desc = np.where(units > 0, desc, 0)
            price = np.round(D_PRECIO * rest['precio_f'] * infl_p * P['precio'], 2)
            cost = np.round(D_COSTE * rest['precio_f'] * infl_c * P['coste'] * (1 + .035 * seasonal), 2)
            net = np.round(units * price * (1 - desc / 100), 2); ctot = np.round(units * cost, 2); marg = np.round(net - ctot, 2)
            for j in range(N_PLATOS):
                emit('rendimiento_platos', dict(zip(FIELDS['rendimiento_platos'], [
                    f'VEN-{rid}-{compact}-{j + 1:02d}', rid, dt, f'PLT-{j + 1:03d}', DISHES[j][0], DISHES[j][1], int(ofertado[j]),
                    float(price[j]), float(cost[j]), int(units[j]), float(desc[j]), float(net[j]), float(ctot[j]), float(marg[j])])))

            # --- RESEÑAS (comentario en texto + puntuación) ----------------------------------
            ocup = clientes / (rest['cap'] * 1.4)
            n_rev = int(rng.poisson(clientes * .022))
            if n_rev and units.sum() > 0:
                for r in range(n_rev):
                    j = int(rng.choice(N_PLATOS, p=units / units.sum()))
                    mu = (3.85 + 2.4 * (D_CALIDAD[j] - .70) + .9 * rest['q'] - 1.8 * max(0, ocup - .85)
                          + P['resena_shift'] - (1.2 * max(0, ocup - .85) if drift else 0))
                    rating = int(np.clip(round(mu + float(rng.normal(0, .95))), 1, 5))
                    plat = rng.choice(PLATAFORMAS[0], p=PLATAFORMAS[1])
                    pun = rating * 2 if plat == 'TheFork' else rating          # TheFork puntúa de 2 a 10 (error sistemático)
                    dias = int(rng.integers(0, 15))
                    emit('resenas', dict(zip(FIELDS['resenas'], [
                        f'RSN-{rid}-{compact}-{r + 1:02d}', rid, dt, (d + timedelta(days=dias)).isoformat(), str(plat),
                        f'PLT-{j + 1:03d}', pun, comentario(rating, DISHES[j][0], ocup, drift)])))
        d += timedelta(days=1)
    for f in files.values():
        f.close()
    return {f'{s}_{nombre}.csv': {'fuente': s, 'lote': nombre, **dict(c)} for s, c in counts.items()}


if __name__ == '__main__':
    manifest = {}
    for nombre, (a, b, drift) in PERIODOS.items():
        manifest.update(gen_periodo(nombre, a, b, drift))
    # --- Resumen enriquecido de los datos y de los errores inyectados ---------------------------
    archivos = {}
    for nombre_f, datos in manifest.items():
        s = datos['fuente']; desc, gran = FUENTES_INFO[s]
        cols_afectadas = {k: ([] if k == 'duplicado' else ['id_restaurante'] if k == 'clave_huerfana'
                              else sorted({c.split('_alt')[0] for c in (RULES[s][k] if isinstance(RULES[s][k], (list, dict)) else [])}))
                          for k in DEF_ERRORES}
        archivos[nombre_f] = {'fuente': s, 'lote': datos['lote'], 'descripcion': desc, 'granularidad': gran, 'clave_primaria': 'id_registro',
                              'n_columnas': len(FIELDS[s]), 'columnas': FIELDS[s],
                              **{k: v for k, v in datos.items() if k not in ('fuente', 'lote')},
                              'bytes': (OUT / nombre_f).stat().st_size,
                              'filas_con_error_de_campo': sum(datos.get(k, 0) for k in DEF_ERRORES if k != 'duplicado'),
                              'columnas_afectadas_por_error': cols_afectadas}
    out = {'semilla': SEED,
           'descripcion': 'Datos sintéticos de restauración (generar_datasets.py) y errores inyectados a propósito.',
           'periodos': {n: {'desde': a.isoformat(), 'hasta': b.isoformat(), 'dias': (b - a).days + 1, 'drift': dr} for n, (a, b, dr) in PERIODOS.items()},
           'restaurantes': {'validos': N_RESTAURANTES, 'primero': 'RST-0001', 'ultimo': f'RST-{N_RESTAURANTES:04d}', 'id_huerfano_inyectado': 'RST-9999'},
           'clientes': {'pool': N_CLIENTES, 'formato_id': 'CLI-NNNNN', 'nota': 'Identificadores seudonimizados sintéticos; no hay datos personales.'},
           'platos': N_PLATOS,
           'nota_conteo': '"filas_csv" = "filas_originales" + "duplicado". Los tipos de error aleatorios son disjuntos entre sí (como máximo uno por fila).',
           'notas_errores_sistematicos': NOTAS,
           'definicion_errores': DEF_ERRORES,
           'archivos': archivos}
    (OUT / 'resumen_ensuciado.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: {'filas_csv': v['filas_csv'], 'bytes': v['bytes']} for k, v in archivos.items()}, ensure_ascii=False, indent=2))
