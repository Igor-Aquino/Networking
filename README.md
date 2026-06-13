# Coleta de VLAN e Subnet via Zabbix (personalização)

Guia prático e direto para descobrir e monitorar **VLANs** e **subnets** de equipamentos de rede (switches/roteadores) no **Zabbix**, usando recursos de personalização: itens SNMP, **Low-Level Discovery (LLD)** e **scripts externos**.

> Testado com **Zabbix 7.0 LTS**. Funciona também no 6.0 LTS e, com pequenos ajustes, no 8.0.

---

## O que você vai conseguir

- Descobrir automaticamente todas as VLANs de um switch e criar um item por VLAN.
- Coletar os endereços IP e máscaras (subnets) configurados nos equipamentos.
- Gerar alertas (triggers) quando uma VLAN sumir ou um IP mudar.
- Entender os três caminhos de personalização: **item SNMP direto**, **LLD** e **script externo**.

---

## Pré-requisitos

- Um servidor Zabbix funcionando (server + frontend).
- SNMP habilitado no equipamento de rede (v2c basta para começar; v3 para produção).
- Pacote de ferramentas SNMP no servidor para testes:

```bash
# Debian/Ubuntu
sudo apt install snmp snmp-mibs-downloader

# RHEL/Rocky/Alma
sudo dnf install net-snmp net-snmp-utils
```

---

## Conceitos rápidos (2 minutos)

- **SNMP**: protocolo que expõe informações do equipamento em "endereços" chamados OIDs.
- **OID**: identificador numérico de uma informação (ex.: nome de VLAN, IP de uma interface).
- **MIB**: o "dicionário" que traduz nomes para OIDs.
- **LLD (Low-Level Discovery)**: recurso do Zabbix que percorre uma tabela SNMP e cria itens/triggers automaticamente, sem você cadastrar um a um.

OIDs que vamos usar:

| Informação | MIB | OID |
|---|---|---|
| Nome das VLANs | Q-BRIDGE-MIB | `1.3.6.1.2.1.17.7.1.4.3.1.1` (`dot1qVlanStaticName`) |
| Endereços IP | IP-MIB | `1.3.6.1.2.1.4.20.1.1` (`ipAdEntAddr`) |
| Máscaras (subnet) | IP-MIB | `1.3.6.1.2.1.4.20.1.3` (`ipAdEntNetMask`) |
| Interface do IP | IP-MIB | `1.3.6.1.2.1.4.20.1.2` (`ipAdEntIfIndex`) |

---

## Passo 1 — Habilitar SNMP no equipamento

Exemplo em um switch Cisco (ajuste para a sua marca):

```
configure terminal
 snmp-server community minhacomunidade RO
 snmp-server location "Datacenter - Rack 3"
exit
write memory
```

> `RO` = somente leitura. Nunca use a community padrão `public` em produção.

---

## Passo 2 — Testar a coleta com snmpwalk

Antes de configurar o Zabbix, **sempre** valide que o equipamento responde. Isso economiza horas de troubleshooting.

```bash
# Listar nomes de VLANs
snmpwalk -v2c -c minhacomunidade 192.168.0.1 1.3.6.1.2.1.17.7.1.4.3.1.1

# Listar IPs configurados
snmpwalk -v2c -c minhacomunidade 192.168.0.1 1.3.6.1.2.1.4.20.1.1

# Listar máscaras (subnets)
snmpwalk -v2c -c minhacomunidade 192.168.0.1 1.3.6.1.2.1.4.20.1.3
```

Saída esperada (exemplo das VLANs):

```
SNMPv2-SMI::mib-2.17.7.1.4.3.1.1.1   = STRING: "default"
SNMPv2-SMI::mib-2.17.7.1.4.3.1.1.10  = STRING: "GERENCIA"
SNMPv2-SMI::mib-2.17.7.1.4.3.1.1.20  = STRING: "SERVIDORES"
SNMPv2-SMI::mib-2.17.7.1.4.3.1.1.30  = STRING: "VOIP"
```

O número final (`1`, `10`, `20`, `30`) é o **ID da VLAN** — é o índice SNMP que o LLD vai usar.

---

## Passo 3 — Cadastrar o host no Zabbix

No frontend: **Data collection → Hosts → Create host**.

- **Host name**: `SW-CORE-01`
- **Interfaces**: adicione uma interface **SNMP**, IP `192.168.0.1`.
- Em **Macros** (aba do host), crie:
  - `{$SNMP_COMMUNITY}` = `minhacomunidade`

Usar macro em vez de digitar a community em cada item é o jeito certo: troca em um lugar só.

---

## Método 1 — Item SNMP direto (personalização simples)

Para coletar **uma** informação específica. Em **Items → Create item**:

- **Type**: `SNMPv2 agent`
- **Key**: `vlan.name.gerencia`
- **SNMP OID**: `1.3.6.1.2.1.17.7.1.4.3.1.1.10` (o `.10` é a VLAN 10)
- **SNMP community**: `{$SNMP_COMMUNITY}`
- **Type of information**: `Character`

Bom para poucos itens fixos. Para "todas as VLANs", use o Método 2.

---

## Método 2 — Low-Level Discovery (o caminho recomendado)

O LLD percorre a tabela de VLANs e cria um item para cada uma, automaticamente. Quando você cria uma VLAN nova no switch, o Zabbix detecta sozinho.

### 2.1 Criar a regra de descoberta

**Discovery rules → Create discovery rule**:

- **Name**: `Descoberta de VLANs`
- **Type**: `SNMPv2 agent`
- **Key**: `vlan.discovery`
- **SNMP OID**: `discovery[{#VLAN_NAME},1.3.6.1.2.1.17.7.1.4.3.1.1]`
- **SNMP community**: `{$SNMP_COMMUNITY}`
- **Update interval**: `1h`

A sintaxe `discovery[{#MACRO},OID]` é nativa do Zabbix: ele gera a macro `{#VLAN_NAME}` com cada valor e `{#SNMPINDEX}` com o ID da VLAN.

### 2.2 Criar o protótipo de item (Item prototype)

Dentro da regra, em **Item prototypes → Create item prototype**:

- **Name**: `VLAN {#SNMPINDEX} - {#VLAN_NAME}`
- **Type**: `SNMPv2 agent`
- **Key**: `vlan.name[{#SNMPINDEX}]`
- **SNMP OID**: `1.3.6.1.2.1.17.7.1.4.3.1.1.{#SNMPINDEX}`
- **SNMP community**: `{$SNMP_COMMUNITY}`
- **Type of information**: `Character`

Pronto: um item por VLAN, criado e mantido automaticamente.

### 2.3 (Opcional) Trigger para VLAN sumindo

Em **Trigger prototypes**:

- **Name**: `VLAN {#VLAN_NAME} sem dados em {HOST.NAME}`
- **Expression**: `nodata(/SW-CORE-01/vlan.name[{#SNMPINDEX}],30m)=1`
- **Severity**: `Warning`

---

## Método 3 — Descoberta de subnets com script externo (personalização total)

Quando a informação não cabe num único OID, ou você quer formatar/cruzar dados, use um **script externo**. O Zabbix roda o script e espera um **JSON de LLD** na saída.

### 3.1 Onde fica o script

Coloque em `/usr/lib/zabbix/externalscripts/` (caminho definido em `ExternalScripts` no `zabbix_server.conf`).

```bash
sudo cp scripts/descobrir_subnets.sh /usr/lib/zabbix/externalscripts/
sudo chown zabbix:zabbix /usr/lib/zabbix/externalscripts/descobrir_subnets.sh
sudo chmod 750 /usr/lib/zabbix/externalscripts/descobrir_subnets.sh
```

O script (incluído neste repo, em [`scripts/descobrir_subnets.sh`](scripts/descobrir_subnets.sh)) faz `snmpwalk` dos IPs e máscaras e devolve um JSON assim:

```json
{
  "data": [
    { "{#IP}": "192.168.0.1", "{#MASK}": "255.255.255.0", "{#SUBNET}": "192.168.0.0/24" },
    { "{#IP}": "10.0.10.1",   "{#MASK}": "255.255.255.0", "{#SUBNET}": "10.0.10.0/24" }
  ]
}
```

### 3.2 Testar o script direto no servidor

```bash
sudo -u zabbix /usr/lib/zabbix/externalscripts/descobrir_subnets.sh 192.168.0.1 minhacomunidade
```

Se o JSON aparecer, está pronto para o Zabbix.

### 3.3 Criar a regra de descoberta usando o script

**Discovery rules → Create discovery rule**:

- **Name**: `Descoberta de Subnets`
- **Type**: `External check`
- **Key**: `descobrir_subnets.sh["{HOST.IP}","{$SNMP_COMMUNITY}"]`
- **Update interval**: `1h`

E um **item prototype** para guardar cada subnet:

- **Name**: `Subnet {#SUBNET} (IP {#IP})`
- **Type**: `Dependent item` (depende da regra) ou `External check`, conforme seu desenho
- **Key**: `subnet.info[{#IP}]`

---

## Verificação final

1. **Latest data** (Monitoring → Latest data) deve listar os itens `VLAN ...` e `Subnet ...`.
2. Crie uma VLAN nova no switch e espere o intervalo do LLD — ela deve aparecer sozinha.
3. Confira em **Reports → Availability** / dashboards se os triggers disparam como esperado.

---

## Troubleshooting

| Sintoma | Causa provável | Solução |
|---|---|---|
| Item "Not supported" | community ou OID errado | Refaça o `snmpwalk` com os mesmos valores |
| LLD não cria itens | OID da tabela errado ou sem permissão | Confira o OID base e a community RO |
| Script externo sem retorno | permissão/owner do arquivo | `chown zabbix:zabbix` e `chmod 750` |
| Timeout SNMP | firewall/UDP 161 bloqueado | Libere UDP 161 entre Zabbix e equipamento |
| VLAN com nome vazio | switch não suporta Q-BRIDGE-MIB | Use a MIB do fabricante (ex.: CISCO-VTP-MIB) |

---

## Estrutura do repositório

```
zabbix-vlan-subnet/
├── README.md                      # este guia
├── scripts/
│   └── descobrir_subnets.sh       # descoberta de subnets via SNMP (JSON LLD)
└── templates/
    └── template_vlan_subnet.md    # passo a passo para montar o template no frontend
```

---

## Referências

- Low-Level Discovery (oficial): https://www.zabbix.com/documentation/current/en/manual/discovery/low_level_discovery
- Itens SNMP no Zabbix: https://www.zabbix.com/documentation/current/en/manual/config/items/itemtypes/snmp

---

*Material de estudo e referência sobre monitoramento de redes. Contribuições e sugestões são bem-vindas — abra uma issue ou um pull request.*
