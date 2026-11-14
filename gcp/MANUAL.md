# Despliegue en Google Cloud paso a paso (equivalente manual de los scripts `gcp/*.sh`)

Todo el sistema (MongoDB, Cassandra, Neo4j, Airflow, Jupyter, Streamlit) corre en Docker dentro de
una sola VM. No se necesita ninguna cuenta externa aparte de Google Cloud.

## 0. Prerrequisitos (10 min)

1. Cuenta de Google Cloud con la prueba gratuita de US$300 activa y un proyecto creado. Anota el
   **ID del proyecto** (selector de proyectos, columna "ID"; no es el nombre).
2. El código en un repositorio Git accesible desde la VM (GitHub, puede ser privado con token).
   Alternativa sin Git: subir la carpeta con `gcloud compute scp --recurse` (ver paso 2).

## 1. Crear la VM (= `01_crear_vm.sh`)

Consola web → ☰ → **Compute Engine → Instancias de VM → Crear instancia** (si pide habilitar la API, acepta).

| Campo | Valor |
|---|---|
| Nombre | `bigdata-vm` |
| Región / Zona | `us-central1` / `us-central1-a` |
| Serie / Tipo de máquina | E2 / `e2-standard-4` (4 vCPU, 16 GB) |
| Disco de arranque → Cambiar | Ubuntu 22.04 LTS (x86/64), Disco persistente balanceado, **50 GB** |
| Firewall | sin marcar HTTP/HTTPS |
| Opciones avanzadas → Redes → Etiquetas de red | `bigdata` |
| Opciones avanzadas → Administración → Automatización → Secuencia de comandos de inicio | el script de abajo |

```bash
#!/bin/bash
if ! command -v docker >/dev/null; then
  apt-get update && apt-get install -y ca-certificates curl git
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
  apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  sysctl -w vm.max_map_count=1048575 && echo "vm.max_map_count=1048575" >> /etc/sysctl.conf
fi
```

**Crear**. Cuando aparezca la IP externa, cópiala.

**Firewall del dashboard**: ☰ → **Red de VPC → Firewall → Crear regla**: nombre `allow-dashboard-8501`,
red `default`, entrada, permitir, destinos "Etiquetas de destino" = `bigdata`, origen `0.0.0.0/0`,
TCP `8501`. Solo el dashboard queda público; el resto se usa por túnel SSH.

Equivalente en Cloud Shell (`>_` arriba a la derecha):
```bash
gcloud compute instances create bigdata-vm --zone=us-central1-a --machine-type=e2-standard-4 \
  --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size=50GB --boot-disk-type=pd-balanced --tags=bigdata
gcloud compute firewall-rules create allow-dashboard-8501 --network=default \
  --allow=tcp:8501 --target-tags=bigdata --source-ranges=0.0.0.0/0
```

## 2. Entrar a la VM y subir el código (= `02_tunel_ssh.sh`)

Opciones, de más simple a más cómoda:

* **Botón SSH** en la fila de la VM (terminal en el navegador). Sirve para instalar todo, pero no
  hace túneles: solo verás el dashboard (`http://IP:8501`).
* **Cloud Shell con túnel** y "Vista previa en la web" (un puerto a la vez):
  `gcloud compute ssh bigdata-vm --zone us-central1-a -- -L 8080:localhost:8080`
* **Laptop con gcloud instalado** (cloud.google.com/sdk, `gcloud auth login` una vez): el mismo
  comando con todos los `-L` (8080 Airflow, 8888 Jupyter, 7474 Neo4j, 8081 Mongo Express, 8083 Cassandra Web, 8501
  dashboard). Es lo que hace `02_tunel_ssh.sh`. Recomendado para grabar el video.

Dentro de la VM:
```bash
git clone <URL-DEL-REPO> proyecto-bigdata && cd proyecto-bigdata
```
Sin Git: desde Cloud Shell sube la carpeta (menú ⋮ → Subir) y luego
`gcloud compute scp --recurse proyecto-bigdata bigdata-vm:~ --zone us-central1-a`.

## 3. Levantar el stack dentro de la VM (= `04_setup_en_vm.sh`)

```bash
# Docker sin sudo (una vez; el startup-script corrió antes de que existiera tu usuario)
sudo usermod -aG docker $USER && newgrp docker
docker info >/dev/null && echo "docker OK"      # si falla: el startup-script sigue instalando, espera 2 min

cd ~/proyecto-bigdata
cp .env.example .env                            # defaults locales; no hay credenciales externas que pegar
mkdir -p data/raw data/processed && chmod -R a+rwX data

docker compose build                            # 5-10 min la primera vez
docker compose up -d
docker compose ps                               # esperar: todos healthy, airflow-init "exited (0)"

docker exec -i cassandra cqlsh < scripts/init_cassandra.cql
docker compose exec -T jupyter python scripts/init_mongo.py
docker compose exec -T jupyter python scripts/init_neo4j.py

docker compose exec -T jupyter bash -c 'cd src && python run_pipeline_local.py'   # carga inicial, 2-5 min
```

Verificar: `http://IP_EXTERNA:8501` muestra KPIs y datos en las 3 pestañas. Con túnel,
`http://localhost:8080` muestra el DAG `github_events_pipeline` activo.

Carga histórica (un día ≈ 85k eventos, ~3 min; necesaria para superar los 50,000 registros):
`docker compose exec jupyter bash -c "cd src && python run_pipeline_local.py 2026-11-09 0 23"`

## 4. Apagar / encender / borrar (= `03_apagar_encender.sh`)

Compute Engine → Instancias de VM → marcar `bigdata-vm` → **Detener / Iniciar / Eliminar**.

* Detenida pagas solo el disco (~US$0.17/día). Al iniciar, los contenedores arrancan solos.
* La IP externa cambia al reiniciar. Para fijarla: Red de VPC → Direcciones IP → fila de la VM → "Reservar".
* Facturación → Presupuestos y alertas → crear presupuesto (p. ej. US$30).
* Al terminar el curso: Eliminar la VM (borra también el disco).

## Costos de referencia (us-central1)

| Concepto | Costo |
|---|---|
| VM e2-standard-4 encendida | ≈ US$0.134/h (US$3.2/día) |
| Disco 50 GB | ≈ US$0.17/día, también apagada |
| IP externa en uso | ≈ US$0.12/día |
| Setup + validación (una tarde) | ≈ US$1 |
| 6 días a 8 h/día | ≈ US$10 |
| 6 días 24/7 | ≈ US$25 |

## Problemas típicos

| Síntoma | Causa | Arreglo |
|---|---|---|
| `permission denied` al usar docker | grupo docker no activo | salir y volver a entrar al SSH |
| `docker: command not found` | startup-script aún instalando | esperar 2-3 min; `sudo journalctl -u google-startup-scripts -f` |
| Cassandra `unhealthy` | arrancando | esperar 2 min; `docker logs cassandra` |
| Neo4j rechaza contraseña | cambiaste `NEO4J_PASSWORD` tras el primer arranque | `docker compose down -v` y volver a levantar |
| Airflow no ve el DAG | scheduler cargando | 1 min; `docker compose restart airflow-scheduler` |
| Dashboard no abre desde internet | falta regla de firewall o etiqueta `bigdata` | revisar paso 1 |
