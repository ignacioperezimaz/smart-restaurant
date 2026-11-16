"""Genera tres fuentes sintéticas, dos lotes temporales y errores reproducibles.
Uso: python generar_datasets.py [directorio] (requiere numpy).
"""
import csv, json, math, sys
from pathlib import Path
from datetime import date, timedelta
from collections import Counter
import numpy as np

SEED = 20261116
OUT = Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).parent
OUT.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(SEED)
err = np.random.default_rng(SEED+1)
DISHES = [
 ('Hamburguesa clásica','Principal',13.5,4.2,1.25),('Pizza margarita','Principal',12.5,3.5,1.10),
 ('Ensalada de temporada','Entrante',9.5,2.8,.78),('Croquetas caseras','Entrante',8.5,2.6,1.15),
 ('Pasta boloñesa','Principal',14.5,4.8,1.05),('Solomillo a la plancha','Principal',24.5,14.5,.44),
 ('Arroz de verduras','Principal',13.0,4.0,.70),('Salmón al horno','Principal',19.0,10.2,.65),
 ('Tarta de queso','Postre',6.5,1.65,.95),('Brownie de chocolate','Postre',6.0,1.7,.66),
 ('Patatas bravas','Entrante',7.0,2.0,1.20),('Sopa del día','Entrante',7.5,3.25,.40)]
CITIES = [('Donostia','Gipuzkoa'),('Bilbao','Bizkaia'),('Vitoria-Gasteiz','Araba'),('Pamplona','Navarra'),('Santander','Cantabria'),('Logroño','La Rioja'),('Burgos','Burgos'),('Oviedo','Asturias')]
FIELDS={
 'afluencia_diaria':['id_registro','id_restaurante','fecha_servicio','ciudad','provincia','tipo_restaurante','capacidad_asientos','dia_semana','mes','temporada','festivo_simulado','evento_local_previsto','temperatura_prevista_c','lluvia_prevista_mm','horas_apertura_planificadas','fecha_corte_prediccion','clientes_reales','clientes_con_reserva_reales','clientes_sin_reserva_reales'],
 'reservas_diarias':['id_registro','id_restaurante','fecha_servicio','turno','fecha_corte_prediccion','reservas_confirmadas_corte','comensales_reservados_corte','reservas_web_corte','reservas_telefono_corte','antelacion_media_dias_corte','comensales_cancelados_final','comensales_no_show_final','comensales_asistentes_final','reservas_nuevas_dia_comensales'],
 'rendimiento_platos':['id_registro','id_restaurante','fecha_servicio','id_plato','nombre_plato','categoria','ofertado','precio_unitario_eur','coste_unitario_eur','unidades_vendidas','descuento_medio_pct','ventas_netas_eur','coste_total_eur','margen_contribucion_eur','canal_venta']}
# Cada anomalía afecta a una fila limpia elegida al azar (categorías disjuntas).
RULES={
 'afluencia_diaria':{
  'nulos':['clientes_reales','temperatura_prevista_c','capacidad_asientos','ciudad','horas_apertura_planificadas'],
  'tipos':{'clientes_reales':'muchos','capacidad_asientos':'sesenta','lluvia_prevista_mm':'lluvia','festivo_simulado':'desconocido'},
  'incorrectos':{'clientes_reales':-18,'capacidad_asientos':0,'mes':14,'horas_apertura_planificadas':29,'dia_semana':'Funday'},
  'outliers':{'clientes_reales':9500,'temperatura_prevista_c':78.1,'lluvia_prevista_mm':900},
  'formatos':['fecha_servicio','fecha_corte_prediccion','temperatura_prevista_c','ciudad'],
  'categorias':{'tipo_restaurante':'  BISTRÓ  ','temporada':'INVIERNO '},
 },
 'reservas_diarias':{
  'nulos':['turno','reservas_confirmadas_corte','comensales_reservados_corte','antelacion_media_dias_corte','comensales_asistentes_final'],
  'tipos':{'reservas_confirmadas_corte':'varias','comensales_reservados_corte':'veinte','antelacion_media_dias_corte':'una semana'},
  'incorrectos':{'comensales_reservados_corte':-8,'reservas_web_corte':-4,'comensales_no_show_final':-3,'antelacion_media_dias_corte':-12},
  'outliers':{'comensales_reservados_corte':5000,'reservas_confirmadas_corte':3000,'antelacion_media_dias_corte':950},
  'formatos':['fecha_servicio','fecha_corte_prediccion','antelacion_media_dias_corte','turno'],
  'categorias':{'turno':' CENA ','turno_alt':'comidA'},
 },
 'rendimiento_platos':{
  'nulos':['id_plato','precio_unitario_eur','coste_unitario_eur','unidades_vendidas','categoria','nombre_plato'],
  'tipos':{'precio_unitario_eur':'gratis?','coste_unitario_eur':'pendiente','unidades_vendidas':'muchas','ofertado':'quizá'},
  'incorrectos':{'precio_unitario_eur':-8.5,'coste_unitario_eur':-3,'unidades_vendidas':-20,'descuento_medio_pct':145,'coste_total_eur':-28},
  'outliers':{'precio_unitario_eur':1800,'unidades_vendidas':12000,'coste_unitario_eur':950},
  'formatos':['fecha_servicio','precio_unitario_eur','coste_unitario_eur','nombre_plato'],
  'categorias':{'categoria':' PRINCIPAL ','canal_venta':'  SALA  '},
 }}
# Fracciones aproximadas de filas originales: 8% errores de campo + 2% duplicados.
LIMITS=[(.025,'nulos'),(.040,'tipos'),(.055,'incorrectos'),(.070,'formatos'),(.075,'outliers'),(.080,'categorias'),(.085,'clave_huerfana'),(.105,'duplicado')]

def rnd_choice(seq): return seq[int(err.integers(len(seq)))]
def corrupt(source, row):
    x=err.random(); kind=next((k for lim,k in LIMITS if x<lim),None)
    if kind is None or kind=='duplicado': return row,kind
    row=row.copy(); rules=RULES[source]
    if kind=='clave_huerfana':
        row['id_restaurante']='RST-9999'; return row,kind
    if kind=='nulos':
        row[rnd_choice(rules[kind])]=rnd_choice(['','NA','NULL','sin dato']); return row,kind
    if kind in ('tipos','incorrectos','outliers'):
        col=rnd_choice(list(rules[kind])); row[col]=rules[kind][col]; return row,kind
    if kind=='categorias':
        col=rnd_choice(list(rules[kind])); col='turno' if col=='turno_alt' else col
        row[col]=' '+str(row[col]).upper()+' '; return row,kind
    col=rnd_choice(rules['formatos']); val=row[col]
    if col=='fecha_servicio':
        y,m,d=val.split('-'); row[col]=rnd_choice([f'{d}/{m}/{y}',f'{y}/{m}/{d}',f'{d}-{m}-{y}','31/02/2025'])
    elif col=='fecha_corte_prediccion':
        row[col]=val.replace('T',' ').replace('-','/')
    elif isinstance(val,(int,float,np.integer,np.floating)):
        row[col]=str(val).replace('.',',')+(' €' if 'eur' in col else '')
    else: row[col]='  '+str(val).upper()+'  '
    return row,kind

restaurants=[]
for i in range(64):
    city,prov=CITIES[i%len(CITIES)]
    restaurants.append((f'RST-{i+1:04d}',city,prov,['casual','bistró','familiar','tradicional'][i%4],int(rng.integers(35,111)),float(rng.uniform(.85,1.18)),rng.uniform(.75,1.25,len(DISHES))))

def gen_period(name,start,end,drift):
    files={s:(OUT/f'{s}_{name}.csv').open('w',encoding='utf-8',newline='') for s in FIELDS}
    writers={s:csv.DictWriter(files[s],fieldnames=FIELDS[s]) for s in FIELDS}
    counts={s:Counter() for s in FIELDS}
    for w in writers.values(): w.writeheader()
    def emit(s,row):
        counts[s]['filas_originales']+=1
        row,kind=corrupt(s,row)
        writers[s].writerow(row)
        if kind: counts[s][kind]+=1
        if kind=='duplicado': writers[s].writerow(row)
        counts[s]['filas_csv']+=1+int(kind=='duplicado')
    d=start
    while d<=end:
        dt=d.isoformat(); compact=dt.replace('-',''); cutoff=(d-timedelta(days=1)).isoformat()+'T23:59:00'
        wd=d.weekday(); month=d.month; season=['invierno','primavera','verano','otoño'][((month%12)//3)]
        holiday=int((month,d.day) in {(1,1),(1,6),(5,1),(8,15),(10,12),(11,1),(12,6),(12,8),(12,25)})
        seasonal=math.sin(2*math.pi*(d.timetuple().tm_yday-85)/365.25)
        for i,(rid,city,prov,typ,cap,price_factor,prefs) in enumerate(restaurants):
            weather=round(14+7.5*seasonal+rng.normal(0,2.5)+(.9 if drift else 0),1)
            rain=round(float(rng.gamma(1.5,3.0)) if rng.random()<(.37 if drift else .28) else 0,1)
            event=int(rng.random()<.045); hours=10 if wd in (4,5) else 8
            demand=cap*(.88+.12*seasonal)*([.78,.83,.90,1.0,1.28,1.43,1.14][wd])*(1+.17*holiday+.24*event-.009*min(rain,25))
            if drift: demand*=.87 if i%3==0 else 1.08
            total_reserved=total_walk=0
            for turn,weight in [('comida',.48),('cena',.52)]:
                reserved=int(rng.poisson(max(1,demand*weight*.67)))
                bookings=min(reserved,max(0,int(round(reserved/rng.uniform(2.1,3.5))))) if reserved else 0
                web=int(rng.binomial(bookings,.70 if drift else .53)); phone=bookings-web
                cancel=int(rng.binomial(reserved,.15 if drift else .075)); noshow=int(rng.binomial(reserved-cancel,.08 if drift else .045))
                new=int(rng.poisson(max(.1,demand*weight*.09))); attended=reserved-cancel-noshow+new
                walk=int(rng.poisson(max(.1,demand*weight*.32)))
                total_reserved+=attended; total_walk+=walk
                emit('reservas_diarias',dict(zip(FIELDS['reservas_diarias'],[f'RES-{rid}-{compact}-{turn}',rid,dt,turn,cutoff,bookings,reserved,web,phone,round(float(rng.uniform(1.2,8.5)),2) if bookings else 0,cancel,noshow,attended,new])))
            visitors=total_reserved+total_walk
            emit('afluencia_diaria',dict(zip(FIELDS['afluencia_diaria'],[f'AFL-{rid}-{compact}',rid,dt,city,prov,typ,cap,['lunes','martes','miércoles','jueves','viernes','sábado','domingo'][wd],month,season,holiday,event,weather,rain,hours,cutoff,visitors,total_reserved,total_walk])))
            # Ventas diarias por plato, no transacciones individuales. Las ventas de platos
            # pueden superar la afluencia porque un comensal pide varios productos.
            for j,(dish,category,base_price,base_cost,pop) in enumerate(DISHES):
                offered=int(rng.random()>.018)
                price=round(base_price*price_factor*(1.04 if d.year>=2025 else 1)*(1.035 if drift else 1),2)
                cost=round(base_cost*price_factor*(1.055 if d.year>=2025 else 1)*(1.12 if drift else 1)*(1+.035*seasonal),2)
                share=pop*prefs[j]*(1+.17*seasonal if j in (2,6) else 1-.10*seasonal if j==11 else 1)
                if drift and j in (2,6): share*=1.20
                units=int(rng.poisson(max(.01,visitors*.125*share))) if offered else 0
                discount=float(rng.choice([0,0,0,0,5,10,15])) if units else 0
                net=round(units*price*(1-discount/100),2); cost_total=round(units*cost,2); margin=round(net-cost_total,2)
                emit('rendimiento_platos',dict(zip(FIELDS['rendimiento_platos'],[f'VEN-{rid}-{compact}-{j+1:02d}',rid,dt,f'PLT-{j+1:03d}',dish,category,offered,price,cost,units,discount,net,cost_total,margin,'sala'])))
        d+=timedelta(days=1)
    for f in files.values(): f.close()
    return {f'{s}_{name}.csv':{**dict(c),'bytes':(OUT/f'{s}_{name}.csv').stat().st_size} for s,c in counts.items()}

if __name__=='__main__':
    manifest={**gen_period('historico',date(2024,1,1),date(2025,12,31),False),**gen_period('lote_drift',date(2026,1,1),date(2026,6,30),True)}
    (OUT/'resumen_ensuciado.json').write_text(json.dumps({'semilla':SEED,'archivos':manifest},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
