#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BME688/ESP32 -> arquivos Bosch .bmerawdata e .bmespecimen (experimental).

Dependencia: pip install pyserial
Captura + previsão ao encerrar: python coletor_bme688_ai_studio_v2.py coletar --porta /dev/ttyUSB0
Conversao: python coletor_bme688_ai_studio_v2.py converter caminho/arquivo.bmerawdata

O arquivo .bmespecimen foi montado conforme o esquema PUBLICADO da Bosch, mas a
importacao em BME AI-Studio 2.2.0 com hardware ESP32 personalizado NAO foi
validada. Nao utilize previsoes de glicemia para decisoes medicas.
"""
import argparse
import csv
import json
import math
import os
import queue
import re
import secrets
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from pathlib import Path

HEATER = [[320,5],[100,2],[100,10],[100,30],[200,5],[200,5],[200,5],[320,5],[320,5],[320,5]]
VERSION = '2.2.0'  # formato documentado, nao uma declaracao sobre sua instalacao
BOARD_TYPE = 'board_1'  # hardware customizado; NAO falsifica como board_8
BOARD_ID = 'ESP32_BME688_01'
FW = 'esp32-bme68x-custom'
DESCRICOES = {
    0: 'Ar ambiente',
    1: 'Halito basal - menos de 2h apos comer',
    2: 'Halito - mais de 2h sem comer',
    3: 'Halito - jejum maior que 8h',
}
KEYS = [
    ('Sensor Index','','integer','sensor_index'),
    ('Sensor ID','','integer','sensor_id'),
    ('Time Since PowerOn','Milliseconds','integer','timestamp_since_poweron'),
    ('Real time clock','Unix Timestamp: seconds since Jan 01 1970. (UTC); 0 = missing','integer','real_time_clock'),
    ('Temperature','DegreesCelcius','float','temperature'),
    ('Pressure','Hectopascals','float','pressure'),
    ('Relative Humidity','Percent','float','relative_humidity'),
    ('Resistance Gassensor','Ohms','float','resistance_gassensor'),
    ('Heater Profile Step Index','','integer','heater_profile_step_index'),
    ('Scanning Mode Enabled','','boolean','scanning_enabled'),
    ('Scanning Cycle Index','','integer','scanning_cycle_index'),
    ('Label Tag','','integer','label_tag'),
    ('Error Code','','integer','error_code'),
]
COLUMNS = [dict(name=n,unit=u,format=f,key=k,colId=i) for i,(n,u,f,k) in enumerate(KEYS,1)]
SPEC_COLUMNS = [
    ('Data Point ID','','integer','data_point_id'),
    ('Resistance Gassensor','Ohms','float','resistance_gassensor'),
    ('Temperature','DegreesCelsius','float','temperature'),
    ('Pressure','Hectopascals','float','pressure'),
    ('Relative Humidity','Percent','float','relative_humidity'),
    ('Time Since PowerOn','Milliseconds','integer','timestamp_since_poweron'),
    ('Real time clock','Unix Timestamp: seconds since Jan 01 1970. (UTC); 0 = missing','integer','real_time_clock'),
    ('Error Code','','integer','error_code'),
    ('Cycle Step Index','','integer','cycle_step_index'),
    ('Cycle ID','','integer','cycle_id'),
]

def now():
    return datetime.now(timezone.utc)

def iso(dt):
    return dt.isoformat(timespec='milliseconds').replace('+00:00','Z')

def dt_from_sec(sec):
    return datetime.fromtimestamp(int(sec), timezone.utc)

def write_atomic(path, data):
    path = Path(path)
    tmp = path.with_name(path.name+'.tmp')
    with open(tmp,'w',encoding='utf-8') as f:
        json.dump(data,f,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

def safe_label(value):
    value = re.sub(r'[^a-z0-9-]+','-',value.lower()).strip('-')
    return value[:55] or 'amostra'

def raw_document(rows, start, board_id, seed):
    return {
        'configHeader': {'dateCreated_ISO':iso(start),'appVersion':VERSION,
                         'boardType':BOARD_TYPE,'boardMode':'heater_profile_exploration','boardLayout':'grouped'},
        'configBody': {
            'heaterProfiles':[{'id':'heater_354','timeBase':140,'temperatureTimeVectors':HEATER}],
            'dutyCycleProfiles':[{'id':'duty_1','numberScanningCycles':1,'numberSleepingCycles':0}],
            'sensorConfigurations':[{'sensorIndex':0,'heaterProfile':'heater_354','dutyCycleProfile':'duty_1'}]},
        'rawDataHeader': {'counterPowerOnOff':1,'seedPowerOnOff':seed,'counterFileLimit':0,
                          'dateCreated':str(int(start.timestamp())),'dateCreated_ISO':iso(start),
                          'firmwareVersion':FW,'boardId':board_id},
        'rawDataBody': {'dataColumns':COLUMNS,'dataBlock':rows}
    }

def parse_serial(line):
    if not line.startswith('DATA,'): return None
    p=line.split(',')
    if len(p)!=8: raise ValueError('Esperados 8 campos')
    ms=int(p[1]); temp,press,hum,gas=map(float,p[2:6]); step=int(p[6]); lab=int(p[7])
    if ms<0 or step not in range(10) or lab not in range(10): raise ValueError('Indices invalidos')
    if not all(math.isfinite(x) for x in (temp,press,hum,gas)) or gas<=0: raise ValueError('Valor nao finito ou gas <= 0')
    return (ms,temp,press,hum,gas,step,lab)

def key_indices(doc):
    return {x['key']:i for i,x in enumerate(doc['rawDataBody']['dataColumns'])}

def complete_cycles(doc):
    """Retorna grupos contiguos 0..9, mesmo label, timestamps progressivos, um sensor.
    Nunca preenche etapas faltantes nem duplica ciclos perdidos.
    """
    ix=key_indices(doc); rows=doc['rawDataBody']['dataBlock']
    groups=[]; group=[]; bad=0
    def validate(g):
        if len(g)!=10: return False
        return ( [int(r[ix['heater_profile_step_index']]) for r in g]==list(range(10))
            and len({r[ix['label_tag']] for r in g})==1
            and len({r[ix['sensor_index']] for r in g})==1
            and all(int(r[ix['error_code']])==0 for r in g)
            and all(int(g[i][ix['timestamp_since_poweron']])<int(g[i+1][ix['timestamp_since_poweron']]) for i in range(9)))
    for row in rows:
        step=int(row[ix['heater_profile_step_index']]); expected=len(group)
        if step==0:
            if group:
                if validate(group): groups.append(group)
                else: bad+=1
            group=[row]
        elif group and step==expected:
            group.append(row)
        else:
            if group: bad+=1
            group=[]
        if len(group)==10:
            if validate(group): groups.append(group)
            else: bad+=1
            group=[]
    if group: bad+=1
    return groups,bad

def segments_from_groups(groups, ix):
    """Une ciclos adjacentes com mesma label; nao mistura aquisicoes distintas."""
    segments=[]; previous_index=None
    for g in groups:
        label=int(g[0][ix['label_tag']]); idx=int(g[0][ix['scanning_cycle_index']])
        if segments and segments[-1]['label']==label and previous_index is not None and idx==previous_index+1:
            segments[-1]['groups'].append(g)
        else:
            segments.append({'label':label,'groups':[g]})
        previous_index=idx
    return segments

def specimen_document(doc, segment, specimen_id, ref_glucose=None, ref_acetone=None):
    ix=key_indices(doc); gs=segment['groups']; flat=[r for g in gs for r in g]
    # Nos exemplos oficiais, startTime/endTime de specimen/cycle usam millis since power-on.
    start_ms=int(flat[0][ix['timestamp_since_poweron']]); end_ms=int(flat[-1][ix['timestamp_since_poweron']])
    start_unix=int(flat[0][ix['real_time_clock']]); end_unix=int(flat[-1][ix['real_time_clock']])
    if end_ms<=start_ms: raise ValueError('Intervalo da amostra nulo')
    header=doc['rawDataHeader']; exported=iso(now()); source_created=header.get('dateCreated_ISO',iso(dt_from_sec(start_unix)))
    # Sessao completa cobre o periodo visivel, nunca declara duracao zero.
    all_rows=doc['rawDataBody']['dataBlock']; clocks=[int(r[ix['real_time_clock']]) for r in all_rows if int(r[ix['real_time_clock']])>0]
    if not clocks: raise ValueError('Rawdata sem relogio real')
    session_start=iso(dt_from_sec(min(clocks))); session_end=iso(dt_from_sec(max(clocks)))
    if min(clocks)==max(clocks):
        session_end=iso(dt_from_sec(max(clocks))+timedelta(seconds=1))
    msid=1; bid=1; hp=1; duty=1; sid=1; cfg=1
    stamp={'createdAt':source_created,'updatedAt':exported}
    label=DESCRICOES.get(segment['label'],f'Condicao_{segment["label"]}')
    metadata=[]
    if ref_glucose is not None: metadata.append({'key':'Glicose de referencia [mg/dL]','value':float(ref_glucose)})
    if ref_acetone is not None: metadata.append({'key':'Acetona de referencia [ppm]','value':float(ref_acetone)})
    cycles=[]; points=[]; point_id=1
    for index,g in enumerate(gs,1):
        cycle_id=index
        cycles.append({'id':cycle_id,'uuid':str(uuid.uuid4()),
                       'startTime':int(g[0][ix['timestamp_since_poweron']]),
                       'endTime':int(g[-1][ix['timestamp_since_poweron']]),
                       'dropped':False,'measurementSessionId':msid,'sensorId':sid,**stamp})
        for row in g:
            points.append([point_id,float(row[ix['resistance_gassensor']]),float(row[ix['temperature']]),
                           float(row[ix['pressure']]),float(row[ix['relative_humidity']]),
                           int(row[ix['timestamp_since_poweron']]),int(row[ix['real_time_clock']]),
                           int(row[ix['error_code']]),int(row[ix['heater_profile_step_index']]),cycle_id])
            point_id+=1
    specimen={'meta':{'appVersion':VERSION,'exportedAt':exported},'data':{
        'specimenData':{'id':specimen_id,'uuid':str(uuid.uuid4()),
                        'comment':'Pesquisa exploratoria com ESP32 + BME688; rotulo experimental nao equivale a concentracao medida.',
                        'startTime':start_ms,'endTime':end_ms,'cloneOfUuid':None,
                        'measurementSessionId':msid,**stamp,'label':label,'metaData':metadata},
        'measurementSession':{'id':msid,'uuid':str(uuid.uuid4()),
                              'name':'Coleta BME688 ESP32','startTime':session_start,'endTime':session_end,
                              'boardId':header.get('boardId',BOARD_ID),**stamp},
        'boardConfig':{'id':cfg,'boardMode':'heater_profile_exploration',
                       'measurementSessionId':msid,'boardTypeId':bid,**stamp},
        'boardType':{'id':bid,'uid':BOARD_TYPE,'name':'ESP32 + BME688 Breakout Board',
                     'numSensors':1,**stamp},
        'heaterProfiles':[{'id':hp,'uid':'heater_354','name':'HP-354','useCase':'',
                           'timeBase':140,'steps':[{'temperature':t,'duration':d} for t,d in HEATER],**stamp}],
        'dutyCycleProfiles':[{'id':duty,'uid':'duty_1','name':'RDC-1-0 Continuous',
                              'description':'Aquisicao continua, sem ciclos de repouso',
                              'energyConsumption':None,'scanningCycles':1,'sleepingCycles':0,**stamp}],
        'sensorConfigs':[{'id':cfg,'boardConfigId':cfg,'sensorId':sid,
                          'heaterProfileId':hp,'dutyCycleProfileId':duty,**stamp}],
        'sensors':[{'id':sid,'index':0,**stamp}],
        'cycles':cycles,
        'dataColumns':[dict(name=n,unit=u,format=f,key=k) for n,u,f,k in SPEC_COLUMNS],
        'specimenDataPoints':points}}
    return specimen

def export_files(doc,out_dir,base_name,refs=None):
    out_dir=Path(out_dir); out_dir.mkdir(parents=True,exist_ok=True)
    ix=key_indices(doc)
    groups,bad=complete_cycles(doc)
    all_rows=doc['rawDataBody']['dataBlock']
    clean_rows=[r for g in groups for r in g]
    raw_all=out_dir/(base_name+'_todas.bmerawdata')
    raw_clean=out_dir/(base_name+'_ciclos_completos.bmerawdata')
    write_atomic(raw_all,doc)
    cleaned=json.loads(json.dumps(doc)); cleaned['rawDataBody']['dataBlock']=clean_rows
    write_atomic(raw_clean,cleaned)
    segments=segments_from_groups(groups,ix)
    exports=[]
    for k,seg in enumerate(segments,1):
        label=seg['label']; ref=(refs or {}).get(str(label),{})
        specimen=specimen_document(doc,seg,k,ref.get('glucose_mg_dl'),ref.get('acetone_ppm'))
        name=f'{safe_label(DESCRICOES.get(label,f"condicao-{label}"))}-{k:03d}_{k}.bmespecimen'
        dest=out_dir/name
        write_atomic(dest,specimen)
        exports.append({'arquivo':name,'label':label,'numero_ciclos':len(seg['groups']),
                        'glucose_referencia':ref.get('glucose_mg_dl'),
                        'acetona_referencia':ref.get('acetone_ppm')})
    report={'leituras':len(all_rows),'ciclos_completos':len(groups),'grupos_incompletos':bad,
            'specimens_gerados':len(exports),'specimens':exports,
            'avisos':['.bmespecimen e produzido conforme esquema publico, nao testado no aplicativo instalado.',
                      'ID de hardware board_1 e personalizado.',
                      'Nenhum valor de glicose/acetona e inferido automaticamente.',
                      'Nao use essas leituras para diagnostico ou conduta clinica.']}
    write_atomic(out_dir/(base_name+'_relatorio.json'),report)
    return report

def receive_commands(q,flag):
    while not flag.is_set():
        try: v=input().strip().lower()
        except EOFError: return
        if v in ('q','sair'): q.put('q');return
        if v in tuple('0123456789'): q.put(v)

def previsoes_apos_coleta(relatorio, pasta, modelo_path):
    """Analisa cada specimen ao final; nenhuma probabilidade é uma medição química."""
    import sys
    try:
        import joblib
        import numpy as np
        # Importar o mesmo extrator de características usado no treinamento.
        from treinar_bme688_multiclasse import features_from_file, COLS
    except ImportError as exc:
        print(f"\n[IA] Não foi possível carregar dependências ou o script de treino: {exc}")
        print("[IA] Coloque treinar_bme688_multiclasse.py na mesma pasta e instale numpy, scikit-learn e joblib.")
        return
    modelo_path = Path(modelo_path).expanduser()
    if not modelo_path.is_file():
        print(f"\n[IA] Modelo não encontrado em {modelo_path}. Dados salvos normalmente.")
        print("[IA] Treine antes: python3 treinar_bme688_multiclasse.py treinar --pasta dados")
        return
    try:
        objeto = joblib.load(modelo_path)  # Abra somente modelo treinado por você.
        modelo = objeto['modelo']
        if objeto.get('campos') != COLS:
            raise ValueError('O modelo usa características diferentes do extrator atual.')
        classes = list(modelo.classes_)
    except Exception as exc:
        print(f"\n[IA] Falha ao carregar modelo: {exc}")
        return

    resultados = []
    for info in relatorio.get('specimens', []):
        arquivo = Path(pasta) / info['arquivo']
        try:
            ciclos, _ = features_from_file(arquivo)
            X = np.asarray([caracteristicas for _, caracteristicas in ciclos], dtype=float)
            prob = modelo.predict_proba(X).mean(axis=0)
            ordenadas = sorted(zip(classes, prob), key=lambda v: v[1], reverse=True)
            print(f"\n{'=' * 54}")
            print(f"[IA] Amostra: {arquivo.name}")
            print(f"[IA] Ciclos completos analisados: {len(ciclos)}")
            print("[IA] Padrões semelhantes às classes de treinamento:")
            for classe, valor in ordenadas:
                print(f"      {classe}: {valor * 100:.1f}%")
            print(f"[IA] Classe mais provável: {ordenadas[0][0]}")
            print("[IA] Essas porcentagens NÃO medem acetona, cetose ou glicemia.")
            resultados.append({'arquivo': arquivo.name, 'ciclos': len(ciclos),
                               'probabilidades_percentuais': {c: round(float(v)*100, 3) for c,v in ordenadas},
                               'classe_mais_provavel': ordenadas[0][0]})
        except Exception as exc:
            print(f"\n[IA] Não foi possível analisar {arquivo.name}: {exc}")
            resultados.append({'arquivo': arquivo.name, 'erro': str(exc)})
    if resultados:
        destino = Path(pasta) / 'previsoes_ia.json'
        write_atomic(destino, {'modelo': str(modelo_path.resolve()), 'resultados': resultados,
            'aviso': 'Classificação exploratória de padrões. Não equivale a acetona em ppm nem a diagnóstico.'})
        print(f"\n[IA] Resultados salvos em: {destino}")


def collect(args):
    try: import serial
    except ImportError: raise SystemExit('Instale pyserial: pip install pyserial')
    start=now(); seed=secrets.token_hex(8); base=start.strftime('%Y_%m_%d_%H_%M')+'_'+secrets.token_hex(3)
    folder=Path(args.saida)/base; folder.mkdir(parents=True,exist_ok=True)
    rows=[]; prevstep=None; prev_ms=None; cycle=-1; q=queue.Queue();stop=threading.Event()
    journal=folder/'serial_e_leituras.csv'; log=folder/'serial_original.log'
    try: ser=serial.Serial(args.porta,args.baud,timeout=1)
    except Exception as e: raise SystemExit(f'Porta serial indisponivel: {e}')
    print('Coleta em',folder.resolve())
    print('Labels: 0=ambiente, 1=basal, 2=mais de 2h, 3=jejum >8h. Digite 0..9 ou q.')
    print('Para glicemia quantitativa, use medida REAL de referencia de mesmo momento.')
    threading.Thread(target=receive_commands,args=(q,stop),daemon=True).start()
    last=time.monotonic()
    try:
        with open(log,'w',encoding='utf-8') as lf,open(journal,'w',encoding='utf-8',newline='') as jf:
            csvw=csv.writer(jf); csvw.writerow(['host_utc','raw_serial','ms','temp_c','press_hpa','umidade_pct','gas_ohm','step','label','ciclo'])
            while True:
                try:
                    cmd=q.get_nowait()
                    if cmd=='q': break
                    ser.write(cmd.encode('ascii'));print('Label enviada:',cmd)
                except queue.Empty: pass
                line=ser.readline().decode('utf-8',errors='replace').strip()
                if line:
                    lf.write(iso(now())+' '+line+'\n');lf.flush()
                try: p=parse_serial(line)
                except Exception as e:
                    print('Linha invalida preservada no log:',e);continue
                if p is not None:
                    ms,temp,press,hum,gas,step,label=p
                    if prev_ms is not None and ms<prev_ms:
                        print('AVISO: ESP32 reiniciou. Encerre sessao para evitar contador de tempo invalido.')
                        break
                    if step==0 and prevstep!=0: cycle+=1
                    elif cycle<0: cycle=0
                    elif prevstep is not None and step!=(prevstep+1)%10: cycle+=1
                    sample_time=now()
                    row=[0,0,ms,int(sample_time.timestamp()),temp,press,hum,gas,step,1,cycle,label,0]
                    rows.append(row)
                    csvw.writerow([iso(sample_time),line,ms,temp,press,hum,gas,step,label,cycle]);jf.flush()
                    prev_ms,prevstep=ms,step
                    print(f'ciclo {cycle} etapa {step} label {label} gas {gas:.1f} ohm',end='\r',flush=True)
                if time.monotonic()-last>=args.checkpoint:
                    write_atomic(folder/'checkpoint.bmerawdata',raw_document(rows,start,args.board_id,seed))
                    last=time.monotonic()
    except KeyboardInterrupt: pass
    finally:
        stop.set();ser.close()
        print('\nSalvando...')
        doc=raw_document(rows,start,args.board_id,seed)
        report=export_files(doc,folder,base)
        print(json.dumps(report,indent=2,ensure_ascii=False))
        print('Arquivos em:',folder.resolve())
        if not args.sem_previsao:
            previsoes_apos_coleta(report, folder, args.modelo)

def convert(args):
    with open(args.arquivo,encoding='utf-8') as f: doc=json.load(f)
    if 'rawDataBody' not in doc: raise SystemExit('Arquivo nao e bmerawdata')
    refs=None
    if args.referencias:
        with open(args.referencias,encoding='utf-8') as f: refs=json.load(f)
    folder=Path(args.saida) if args.saida else Path(args.arquivo).with_suffix('').with_name(Path(args.arquivo).stem+'_exportacao')
    result=export_files(doc,folder,Path(args.arquivo).stem,refs)
    print(json.dumps(result,indent=2,ensure_ascii=False))
    print('Arquivos em:',folder.resolve())

def main():
    ap=argparse.ArgumentParser(description='Coleta/convert BME688 ESP32 para BME AI Studio')
    subs=ap.add_subparsers(dest='acao',required=True)
    cap=subs.add_parser('coletar');cap.add_argument('--porta',default='COM3');cap.add_argument('--baud',type=int,default=115200)
    cap.add_argument('--saida',default='coletas_bme688');cap.add_argument('--board-id',default=BOARD_ID)
    cap.add_argument('--checkpoint',type=int,default=30)
    cap.add_argument('--modelo',type=Path,default=Path('modelo_bme688.joblib'),help='Modelo multiclasse já treinado')
    cap.add_argument('--sem-previsao',action='store_true',help='Somente coletar e salvar sem rodar a IA')
    cap.set_defaults(func=collect)
    con=subs.add_parser('converter');con.add_argument('arquivo');con.add_argument('--saida')
    con.add_argument('--referencias',help='JSON com glicose/acetona de referencia por label: {"2":{"glucose_mg_dl":120}}')
    con.set_defaults(func=convert)
    args=ap.parse_args();args.func(args)

if __name__=='__main__':main()
