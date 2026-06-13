#!/usr/bin/env python3
"""
net_inventory.py — Inventário de rede via SNMP

Varre uma gama de endereços IP (um host ou uma sub-rede em notação CIDR),
consulta cada equipamento por SNMP e gera um inventário em CSV e JSON com:
nome (sysName), descrição/modelo (sysDescr), uptime, contacto, localização
e número de interfaces.

Autor: Igor Aquino
Licença: MIT

A community SNMP NUNCA deve ficar escrita no código nem no repositório.
Passe-a por argumento (--community) ou pela variável de ambiente SNMP_COMMUNITY.

Exemplos:
  # um único equipamento
  python net_inventory.py 192.168.0.1 --community minhacomunidade

  # uma sub-rede inteira, lendo a community do ambiente
  export SNMP_COMMUNITY=minhacomunidade
  python net_inventory.py 192.168.0.0/24

  # porta e ficheiros de saída personalizados
  python net_inventory.py 10.0.0.0/28 -c publica --port 161 --output inventario

Nota sobre segurança: o SNMP v2c usa uma "community" em texto simples. Para
ambientes de produção, considere o SNMPv3 (utilizador + autenticação + cifra).
Este projeto usa v2c por simplicidade; o suporte a v3 fica como melhoria futura.
"""

import os
import sys
import csv
import json
import asyncio
import argparse
import ipaddress
from datetime import datetime

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine,
    CommunityData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    get_cmd,
)

# OIDs do grupo "system" (RFC 1213) + número de interfaces
OIDS = {
    "sysDescr": "1.3.6.1.2.1.1.1.0",
    "sysUpTime": "1.3.6.1.2.1.1.3.0",
    "sysContact": "1.3.6.1.2.1.1.4.0",
    "sysName": "1.3.6.1.2.1.1.5.0",
    "sysLocation": "1.3.6.1.2.1.1.6.0",
    "ifNumber": "1.3.6.1.2.1.2.1.0",
}

CAMPOS = ["ip", "sysName", "sysDescr", "uptime", "sysContact", "sysLocation", "ifNumber"]


def formatar_uptime(ticks):
    """Converte TimeTicks (centésimos de segundo) em algo legível."""
    try:
        ticks = int(ticks)
    except (TypeError, ValueError):
        return ""
    segundos = ticks // 100
    dias, resto = divmod(segundos, 86400)
    horas, resto = divmod(resto, 3600)
    minutos, _ = divmod(resto, 60)
    return f"{dias}d {horas}h {minutos}m"


def expandir_alvos(alvo):
    """Aceita um IP único ou uma sub-rede CIDR e devolve a lista de IPs."""
    try:
        if "/" in alvo:
            rede = ipaddress.ip_network(alvo, strict=False)
            return [str(ip) for ip in rede.hosts()]
        return [str(ipaddress.ip_address(alvo))]
    except ValueError as exc:
        sys.stderr.write(f"Alvo inválido '{alvo}': {exc}\n")
        sys.exit(2)


async def consultar_host(engine, ip, community, port, timeout, retries):
    """Consulta um host. Devolve um dict com os dados ou None se não responder."""
    try:
        target = await UdpTransportTarget.create((ip, port), timeout=timeout, retries=retries)
    except Exception:
        return None

    obj_types = [ObjectType(ObjectIdentity(oid)) for oid in OIDS.values()]
    errInd, errStat, errIdx, varBinds = await get_cmd(
        engine,
        CommunityData(community, mpModel=1),  # mpModel=1 => SNMP v2c
        target,
        ContextData(),
        *obj_types,
    )

    if errInd or errStat:
        return None

    valores = {oid_nome: vb[1].prettyPrint() for oid_nome, vb in zip(OIDS.keys(), varBinds)}
    return {
        "ip": ip,
        "sysName": valores.get("sysName", ""),
        "sysDescr": valores.get("sysDescr", ""),
        "uptime": formatar_uptime(valores.get("sysUpTime")),
        "sysContact": valores.get("sysContact", ""),
        "sysLocation": valores.get("sysLocation", ""),
        "ifNumber": valores.get("ifNumber", ""),
    }


async def varrer(alvos, community, port, timeout, retries, workers):
    engine = SnmpEngine()
    semaforo = asyncio.Semaphore(workers)
    resultados = []

    async def tarefa(ip):
        async with semaforo:
            dados = await consultar_host(engine, ip, community, port, timeout, retries)
            if dados:
                print(f"  [OK] {ip:<16} {dados['sysName']}  ({dados['sysDescr'][:40]})")
                resultados.append(dados)

    await asyncio.gather(*(tarefa(ip) for ip in alvos))
    engine.close_dispatcher()
    resultados.sort(key=lambda d: ipaddress.ip_address(d["ip"]))
    return resultados


def escrever_saidas(resultados, prefixo):
    csv_path = f"{prefixo}.csv"
    json_path = f"{prefixo}.json"

    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CAMPOS)
        writer.writeheader()
        writer.writerows(resultados)

    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(
            {"gerado_em": datetime.now().isoformat(timespec="seconds"),
             "total": len(resultados),
             "equipamentos": resultados},
            fh, ensure_ascii=False, indent=2,
        )

    return csv_path, json_path


def main():
    parser = argparse.ArgumentParser(
        description="Inventário de rede via SNMP (gera CSV e JSON)."
    )
    parser.add_argument("alvo", help="IP único (192.168.0.1) ou sub-rede CIDR (192.168.0.0/24)")
    parser.add_argument("-c", "--community",
                        default=os.environ.get("SNMP_COMMUNITY", "public"),
                        help="Community SNMP (ou variável de ambiente SNMP_COMMUNITY)")
    parser.add_argument("--port", type=int, default=161, help="Porta SNMP (predefinição 161)")
    parser.add_argument("--timeout", type=float, default=1.5, help="Timeout por host (s)")
    parser.add_argument("--retries", type=int, default=1, help="Tentativas por host")
    parser.add_argument("--workers", type=int, default=50, help="Consultas em paralelo")
    parser.add_argument("--output", default="inventario", help="Prefixo dos ficheiros de saída")
    args = parser.parse_args()

    alvos = expandir_alvos(args.alvo)
    print(f"A varrer {len(alvos)} endereço(s) com SNMP v2c na porta {args.port}...\n")

    resultados = asyncio.run(
        varrer(alvos, args.community, args.port, args.timeout, args.retries, args.workers)
    )

    if not resultados:
        print("\nNenhum equipamento respondeu. Verifique a community, a porta e a ligação de rede.")
        sys.exit(1)

    csv_path, json_path = escrever_saidas(resultados, args.output)
    print(f"\n{len(resultados)} equipamento(s) inventariado(s).")
    print(f"  CSV : {csv_path}")
    print(f"  JSON: {json_path}")


if __name__ == "__main__":
    main()
