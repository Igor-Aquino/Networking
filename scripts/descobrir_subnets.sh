#!/usr/bin/env bash
#
# descobrir_subnets.sh
# Descobre os endereços IP e máscaras (subnets) de um equipamento via SNMP
# e devolve um JSON no formato de Low-Level Discovery do Zabbix.
#
# Uso:
#   ./descobrir_subnets.sh <IP_DO_EQUIPAMENTO> <COMMUNITY>
#
# Exemplo:
#   ./descobrir_subnets.sh 192.168.0.1 minhacomunidade
#
# Saída (exemplo):
#   { "data": [ { "{#IP}": "192.168.0.1", "{#MASK}": "255.255.255.0", "{#SUBNET}": "192.168.0.0/24" } ] }

set -euo pipefail

HOST="${1:?Informe o IP do equipamento}"
COMMUNITY="${2:?Informe a community SNMP}"

OID_IP="1.3.6.1.2.1.4.20.1.1"    # ipAdEntAddr
OID_MASK="1.3.6.1.2.1.4.20.1.3"  # ipAdEntNetMask

# Converte uma máscara decimal (255.255.255.0) para prefixo CIDR (24)
mask_to_cidr() {
    local mask="$1" cidr=0 octet
    IFS='.' read -r o1 o2 o3 o4 <<< "$mask"
    for octet in "$o1" "$o2" "$o3" "$o4"; do
        case "$octet" in
            255) cidr=$((cidr+8));; 254) cidr=$((cidr+7));; 252) cidr=$((cidr+6));;
            248) cidr=$((cidr+5));; 240) cidr=$((cidr+4));; 224) cidr=$((cidr+3));;
            192) cidr=$((cidr+2));; 128) cidr=$((cidr+1));; 0) ;;
        esac
    done
    echo "$cidr"
}

# Calcula o endereço de rede a partir de IP + máscara
network_addr() {
    local ip="$1" mask="$2"
    IFS='.' read -r i1 i2 i3 i4 <<< "$ip"
    IFS='.' read -r m1 m2 m3 m4 <<< "$mask"
    echo "$((i1 & m1)).$((i2 & m2)).$((i3 & m3)).$((i4 & m4))"
}

# Coleta IPs e máscaras
mapfile -t IPS  < <(snmpwalk -v2c -c "$COMMUNITY" -Ovq "$HOST" "$OID_IP"   2>/dev/null | tr -d '"')
mapfile -t MASKS < <(snmpwalk -v2c -c "$COMMUNITY" -Ovq "$HOST" "$OID_MASK" 2>/dev/null | tr -d '"')

printf '{ "data": [\n'
first=1
for idx in "${!IPS[@]}"; do
    ip="${IPS[$idx]}"
    mask="${MASKS[$idx]:-255.255.255.255}"
    [ -z "$ip" ] && continue
    cidr=$(mask_to_cidr "$mask")
    net=$(network_addr "$ip" "$mask")
    [ $first -eq 0 ] && printf ',\n'
    printf '  { "{#IP}": "%s", "{#MASK}": "%s", "{#SUBNET}": "%s/%s" }' "$ip" "$mask" "$net" "$cidr"
    first=0
done
printf '\n] }\n'
