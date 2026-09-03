# Mexicanos en Europa

Monitor multilingüe de noticias sobre futbolistas mexicanos en Europa.

**Esta versión está diseñada para funcionar 100% en GitHub.**
No necesitas instalar Python, abrir CMD ni dejar tu computadora encendida.

## Qué hace

Cada hora, GitHub Actions:

1. Busca noticias que mencionen a cualquiera de los jugadores configurados.
2. Busca cobertura internacional y no limita los resultados a un solo idioma.
3. Abre la nota original cuando es posible.
4. Extrae el título, autor, fecha y cuerpo del artículo.
5. Verifica que el nombre del jugador realmente aparezca en el texto extraído.
6. Traduce automáticamente el título y el cuerpo al español.
7. Guarda el texto original y la traducción.
8. Elimina duplicados por URL.
9. Actualiza:
   - `data/articles.json`
   - `docs/feed.xml`
   - `docs/index.html`
   - `docs/players/*.xml`
10. Hace commit automáticamente de los cambios al repositorio.

## RSS creados

### RSS general

`docs/feed.xml`

Incluye noticias de todos los jugadores.

### RSS individuales

Dentro de:

`docs/players/`

Ejemplos:

- `docs/players/obed-vargas.xml`
- `docs/players/edson-alvarez.xml`
- `docs/players/santiago-gimenez.xml`
- `docs/players/raul-jimenez.xml`

Cada feed contiene solamente noticias relacionadas con ese jugador.

## Traducción automática

La búsqueda es multilingüe.

La nota puede encontrarse originalmente en:

- español
- inglés
- portugués
- italiano
- francés
- neerlandés
- ruso
- alemán
- u otros idiomas detectados por las fuentes de descubrimiento

Antes de generar el RSS, el programa intenta traducir automáticamente a español:

- título
- cuerpo completo extraído

En `data/articles.json` se conservan ambos:

- `original_title`
- `original_body`
- `rss_title`
- `rss_body`
- `translated_to`
- `translation_status`

El RSS utiliza `rss_title` y `rss_body`.

Si una traducción falla temporalmente, la noticia no se pierde. Se utiliza el original como respaldo.

## Jugadores configurados

### España

- Obed Vargas — Atlético de Madrid
- Álvaro Fidalgo — Real Betis
- Alex Padilla — Athletic Club

### Inglaterra

- Julián Araujo — Bournemouth
- Edson Álvarez — West Ham United
- Raúl Jiménez — Wolverhampton Wanderers

### Portugal y Países Bajos

- Santiago Giménez — Porto
- Patricio Salas — Famalicao
- Mateo Chávez — AZ Alkmaar
- Stephano Carrillo — Feyenoord (Sub-21)

### Italia, Rusia, Grecia, Dinamarca y Bélgica

- Johan Vásquez — Genoa
- César Montes — Lokomotiv de Moscú
- Luis Chávez — Dinamo de Moscú
- Armando González — Olympiacos
- Rodrigo Huescas — Copenhague
- Heriberto Jurado — Cercle Brugge

### Otras ligas

- Aldahir Valenzuela — Dundee FC
- Armando León — NK Osijek
- Antonio Portales — PAC Omonia 29M
- Jorge Guzmán — FK Željezničar
- Anwar Hernández — Inter Club d'Escaldes

## Cómo instalarlo en GitHub

### 1. Crea un repositorio

En GitHub:

**New repository**

Nombre recomendado:

`mexicanos-en-europa`

### 2. Sube los archivos

Sube directamente el contenido de este ZIP.

En la página principal del repositorio debes ver directamente:

- `main.py`
- `config.json`
- `requirements.txt`
- `README.md`
- `.github`
- `data`
- `docs`

No debe existir otra carpeta `mexicanos-en-europa` por encima de esos archivos.

### 3. Verifica el workflow

Debe existir exactamente:

`.github/workflows/update.yml`

Después entra a:

**Actions**

y deberías ver:

**Update Mexicanos en Europa RSS**

### 4. Ejecuta la primera actualización

Ve a:

**Actions → Update Mexicanos en Europa RSS → Run workflow**

Presiona:

**Run workflow**

La primera ejecución puede tardar más porque todavía no existe un historial de artículos.

Si todo funciona, el workflow terminará en verde.

### 5. Revisa los resultados

Después de terminar:

`data/articles.json`

deberá contener las noticias recopiladas.

Y:

`docs/feed.xml`

será el RSS general.

## Automatización

El archivo:

`.github/workflows/update.yml`

está configurado para ejecutarse automáticamente una vez por hora.

Actualmente:

`23 * * * *`

Eso significa aproximadamente al minuto 23 de cada hora.

No necesitas tener tu computadora encendida.

## Publicar el RSS en Internet

Si quieres que un lector RSS externo pueda abrir directamente una URL como:

`https://TU-USUARIO.github.io/mexicanos-en-europa/feed.xml`

haz el repositorio público y activa GitHub Pages:

1. `Settings`
2. `Pages`
3. `Build and deployment`
4. `Deploy from a branch`
5. Branch: `main`
6. Folder: `/docs`
7. `Save`

GitHub publicará el contenido de `docs`.

Tu RSS general normalmente quedará en:

`https://TU-USUARIO.github.io/mexicanos-en-europa/feed.xml`

y los individuales en:

`https://TU-USUARIO.github.io/mexicanos-en-europa/players/obed-vargas.xml`

etc.

Si mantienes el repositorio privado, los archivos seguirán actualizándose mediante Actions, pero no tendrás una URL pública de GitHub Pages en el plan gratuito.

## Archivos importantes

### `config.json`

Lista de jugadores y configuración del monitor.

### `main.py`

Todo el proceso de búsqueda, extracción, traducción, deduplicación y generación de RSS.

### `.github/workflows/update.yml`

Hace que GitHub ejecute todo automáticamente.

### `data/articles.json`

Base de datos sencilla de noticias encontradas.

### `docs/feed.xml`

RSS general.

### `docs/players/`

Feeds individuales por jugador.

## No necesitas hacer esto

Esta versión NO requiere:

- instalar Python en Windows
- crear `.venv`
- usar CMD
- ejecutar archivos `.bat`
- dejar una computadora encendida
- pagar una API
- pagar un servidor

GitHub Actions ejecuta el proyecto por ti.
