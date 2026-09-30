# Radar Inmobiliario — Huelva y Sevilla

Agente que vigila los portales inmobiliarios y avisa por Telegram cuando aparece
un anuncio nuevo o cambia el precio de uno que ya seguía.

**Criterios que se notifican** (configurables en `config.json`):

| Criterio | Valor |
|---|---|
| Provincias | Huelva, Sevilla |
| Precio | < 300.000 € |
| Dormitorios | ≥ 3 |
| Baños | ≥ 2 |
| Estado | no ocupado |
| Tipo | cualquier vivienda (pisos, áticos, chalets, casas…) |

---

Funciona en **GitHub Actions**, así que no necesita que tu ordenador esté
encendido. Puedes lanzarlo a mano desde el móvil y escribirle comandos al bot.

---

## Puesta en marcha en GitHub Actions

### 1. Configurar Telegram

```bash
.venv\Scripts\python.exe run.py telegram-setup
```

El comando te guía paso a paso. Resumen:

1. En Telegram, habla con **@BotFather** y envía `/newbot`.
2. Copia el token que te da en el fichero `.env` (créalo a partir de `.env.example`).
3. Escríbele **cualquier mensaje a tu bot nuevo** (es lo que le permite responderte).
4. Vuelve a ejecutar `telegram-setup`: te dirá tu `chat_id` para ponerlo en `.env`.
5. Ejecútalo una tercera vez y te llegará un mensaje de prueba.

### 2. Qué se sube al repositorio y qué no

El reparto es: **`main` lleva el código, la rama `estado` lleva los datos.**

| Se sube a `main` | Se queda fuera | Por qué |
|---|---|---|
| `radar/`, `run.py`, `config.json` | | El programa y tus criterios |
| `.github/workflows/radar.yml` | | Sin esto Actions no hace nada |
| `requirements.txt` | | Para que GitHub instale las librerías |
| `.env.example` | | Plantilla, sin credenciales |
| | **`.env`** | **Tu token de Telegram. Nunca.** |
| | `.venv/` | Se reconstruye con `requirements.txt` |
| | `data/` | La base de datos vive en la rama `estado` |

De todo eso, lo único crítico es `.env`. El `.gitignore` ya lo excluye, pero
antes de subir nada compruébalo tú mismo:

```bash
git add -A; git status --short
```

Si `.env` no aparece en esa lista, tu token está a salvo. Deberían salir unos 26
ficheros y ocupar ~155 KB.

La base de datos se queda fuera a propósito: son 3,4 MB que cambian cada hora, y
si se subieran a `main` cada commit dejaría una copia en el historial para
siempre. El workflow la guarda comprimida (menos de 1 MB) en una rama aparte
llamada `estado`, que reescribe entera en cada pasada, así que ese historial
nunca crece. No tienes que crear esa rama: la crea el workflow solo.

### 3. Crear el repositorio y subirlo

Créalo en [github.com/new](https://github.com/new). **Sin** README, sin
`.gitignore` y sin licencia: el repositorio tiene que estar vacío o el primer
push chocará.

**Hazlo público.** El motivo es de cuota: en repositorios públicos los minutos de
Actions son ilimitados, mientras que en privados tienes 2.000 al mes y esto se
queda en ~1.900, sin margen. Lo que se publica es código y unos criterios de
búsqueda; el token va en Secrets, nunca en el repo. Si lo prefieres privado, más
abajo explico qué ajustar.

```bash
git commit -m "Radar inmobiliario"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/radar-inmobiliario.git
git push -u origin main
```

### 4. Guardar el token en Secrets

En tu repositorio: **Settings › Secrets and variables › Actions › New repository
secret**. Dos secretos, uno cada vez:

| Name | Secret |
|---|---|
| `TELEGRAM_BOT_TOKEN` | el token de @BotFather, tal cual (`123456789:AAF...`) |
| `TELEGRAM_CHAT_ID` | tu chat id, solo el número |

Los nombres tienen que escribirse **exactamente así**, en mayúsculas: el workflow
los busca por ese nombre. Sin comillas y sin espacios alrededor del valor.

Una vez guardados no podrás volver a verlos, solo reemplazarlos. Es lo normal:
GitHub los cifra y los oculta también en los logs de ejecución.

### 5. Activar Actions y arrancarlo

1. Pestaña **Actions**. Si es un repo nuevo te pedirá confirmación con un botón
   tipo *"I understand my workflows, go ahead and enable them"*. Acéptalo.
2. En la lista de la izquierda aparece **Radar inmobiliario**. Ábrelo.
3. Botón **Run workflow** a la derecha › déjalo en la rama `main` › **Run workflow**.

La primera pasada hace un barrido completo (unos 16 minutos), construye la línea
base y **no te notifica nada**. Es intencionado: si no, te llegarían miles de
avisos de golpe. A partir de ahí ya funciona solo, cada 30 minutos entre las
08:00 y las 23:30.

### 6. Comprobar que ha ido bien

En la ejecución, despliega el paso **Ejecutar el radar**. Deberías ver líneas
como `fotocasa/Huelva: 1219 vistos, 840 cumplen`. Y al final, en **Guardar el
estado**, un `estado guardado`.

Señales de que algo no va:

| Lo que ves | Qué pasa |
|---|---|
| `Telegram sin configurar` | Los secretos no están, o el nombre está mal escrito |
| `0 vistos` en las tres fuentes | GitHub tiene la IP bloqueada por los portales |
| El paso falla en rojo | Abre el log; el error concreto sale ahí |

> Con el repo **público**, GitHub desactiva los workflows programados tras 60 días
> sin actividad en el repositorio. El radar escribe su estado en cada pasada, así
> que eso cuenta como actividad y no debería pasarte.

---

## Usarlo desde el móvil

**Comandos de Telegram** — escríbeselos al bot:

| Comando | Qué hace |
|---|---|
| `/buscar` | Fuerza un barrido ahora y te cuenta lo que salga |
| `/listar` | Los 10 más baratos que cumplen (acepta un número: `/listar 20`) |
| `/estado` | Cuántos anuncios sigue y cómo fueron las últimas pasadas |
| `/criterios` | Qué está buscando exactamente |
| `/ayuda` | La lista de comandos |

**Importante sobre la latencia:** GitHub Actions no puede tener un proceso
escuchando permanentemente, así que el bot lee tus mensajes cada vez que se
ejecuta el workflow. Un comando tarda en contestarse **hasta 30 minutos**. No es
un bot conversacional; es un vigilante al que puedes dejarle recados.

Si necesitas respuesta inmediata, pulsa **Run workflow** en la app de GitHub para
móvil: eso lanza la pasada al momento y tus comandos se atienden en cuanto
arranca.

El bot **solo obedece a tu `chat_id`**. Cualquier otro que dé con él y le escriba
es ignorado.

---

## Cuánto gasta

Cifras medidas de verdad sobre estos portales, no estimadas:

| Concepto | Duración real | Al mes |
|---|---|---|
| Pasada que solo atiende comandos (32/día) | ~15 s + arranque del runner | ~960 min |
| Barrido rápido, Fotocasa y pisos.com (15/día) | ~40 s | ~450 min |
| Barrido completo, los tres portales (1/día) | **~16 min** | ~480 min |
| **Total** | | **~1.900 min** |

Ojo con la facturación: GitHub **redondea cada job al minuto**, así que una pasada
de 15 segundos te cuesta un minuto entero. De ahí que atender comandos sea, con
diferencia, el mayor gasto.

Eso cabe en los 2.000 minutos del plan gratuito de un repo privado, pero con un
margen ridículo: cualquier reintento o barrido que se alargue te deja sin cuota
a final de mes. En **repositorio público los minutos son ilimitados** y te olvidas
del tema. Por eso lo recomiendo.

Si aun así lo quieres privado, edita `.github/workflows/radar.yml` y `config.json`:

- Cambia el cron a `0 6-21 * * *` (una vez por hora en vez de cada media hora).
- Sube `minutos_entre_rapidos` a `120` y `horas_entre_completos` a `48`.

Quedaría en unas 800 min/mes con holgura, a costa de que los comandos tarden
hasta una hora y los anuncios nuevos se detecten cada dos.

---

## Alternativa: en tu ordenador

Si algún día quieres volver a ejecutarlo en local, los scripts siguen ahí:

```bash
powershell -ExecutionPolicy Bypass -File instalar-tareas.ps1
```

Registra dos tareas de Windows: una rápida cada hora (08:00-22:00) y un barrido
completo diario a las 03:15. Para quitarlas, añade `-Desinstalar`.

---

## Comandos

```bash
.venv\Scripts\python.exe run.py ciclo                # comandos + escaneo si toca (GitHub Actions)
.venv\Scripts\python.exe run.py ciclo --forzar rapido # ignora el intervalo y escanea ya
.venv\Scripts\python.exe run.py vigilar              # barrido rápido + aviso
.venv\Scripts\python.exe run.py vigilar --completo   # barrido entero
.venv\Scripts\python.exe run.py vigilar --sin-avisar # prueba, no manda nada
.venv\Scripts\python.exe run.py bot                  # lee y contesta comandos de Telegram
.venv\Scripts\python.exe run.py estado               # qué hay en la base de datos
.venv\Scripts\python.exe run.py listar               # anuncios que cumplen, por precio
.venv\Scripts\python.exe run.py verificar            # confirma que no están ocupados
.venv\Scripts\python.exe run.py probar-fuentes       # ¿siguen legibles los portales?
```

---

## Fuentes

Se comprobó el acceso real de los portales grandes antes de elegir:

| Portal | Estado | Por qué |
|---|---|---|
| **Fotocasa** | ✅ en uso | La mejor. Trae un JSON estructurado con los flags `isOccupied`, `isRentedWithTenants`, `isAuctioned` y `isBareOwnership`, y acepta filtros y orden por fecha en la propia URL. |
| **pisos.com** | ✅ en uso | HTML estable, precio limpio, filtro de precio y orden por fecha en la URL. |
| **Habitaclia** | ✅ solo en barrido completo | Datos buenos, con dos limitaciones. Va **por municipios**: su página provincial usa `/vistamapa.htm`, que su `robots.txt` prohíbe (los municipios vigilados están en `config.json`). Y **no admite ordenar por fecha**: su `robots.txt` también prohíbe el parámetro `ordenar=`, así que en un barrido rápido no hay forma de saber en qué página ha caído un anuncio recién publicado. Por eso solo entra en el barrido completo diario. |
| **Idealista** | ❌ descartado | Devuelve HTTP 403 (protección DataDome). Su API oficial exige aprobación previa y el nivel gratuito ronda las 100 llamadas al mes, insuficiente para vigilar. |
| **yaencontre** | ❌ descartado | También bloqueado por DataDome. |

Se respeta el `robots.txt` de cada portal, se identifica el cliente y se espera
2 segundos entre peticiones. Si aun así te preocupa el uso, sube
`segundos_entre_peticiones` en `config.json`.

---

## Cómo decide si un piso está ocupado

Es el criterio más delicado, porque es el que más ruido produce si falla. Se hace
en tres capas:

1. **Flags del portal.** Fotocasa expone campos explícitos de ocupación; se usan
   con prioridad sobre cualquier otra señal.
2. **Texto de la tarjeta y de la URL.** Se buscan las fórmulas habituales del
   sector: *sin posesión*, *no visitable*, *con inquilinos*, *nuda propiedad*,
   *proindiviso*, *subasta*, *okupas*… Las señales inequívocas de ocupación se
   evalúan **antes** que las de disponibilidad, para que un anuncio que dice a la
   vez «vivienda ocupada» y «concertar visita» se clasifique bien. Y se manejan
   las negaciones: *«no se puede visitar»* no se confunde con *«se puede visitar»*.
3. **Ficha completa, solo antes de avisar.** Las tarjetas del listado recortan la
   descripción con puntos suspensivos, y la letra pequeña vive justo ahí. Por eso,
   de los pocos anuncios que están a punto de notificarse se abre la ficha entera
   y se vuelve a comprobar.

Esa tercera capa no es un lujo: al probarla sobre los 60 anuncios más baratos del
catálogo inicial, **29 resultaron estar ocupados**. Casi la mitad. Los pisos muy
por debajo de mercado son en su mayoría stock de banco sin posesión.

Cuando un anuncio no dice nada, se notifica igualmente pero marcado con
`⚠️ ocupación no confirmada`. Si prefieres no verlos, pon
`"incluir_ocupacion_desconocida": false` en `config.json`.

---

## Cuánto vas a recibir

Con los criterios actuales hay **unos 5.400 anuncios** que cumplen en las dos
provincias. Eso es el catálogo, no lo que te llega: solo se notifican las
novedades.

Midiendo las fechas de publicación de Fotocasa, aparecen **unos 6 anuncios
nuevos al día** que encajan (34 en la última semana en Huelva, 9 en Sevilla).
Sumando los otros dos portales y quitando duplicados, cuenta con **10-15 avisos
diarios**, más las bajadas de precio.

Si te resulta mucho, lo que más recorta sin perder calidad es subir
`dormitorios_min` a 4, bajar `precio_max`, o poner
`"incluir_ocupacion_desconocida": false` para quedarte solo con los que
confirman que se entregan libres.

---

## Cómo está montado en GitHub Actions

Un **único workflow** hace las dos cosas. Podría haber uno para los comandos y
otro para escanear, pero entonces dos ejecuciones podrían solaparse y pisarse al
guardar el estado. Así que cada pasada:

1. Recupera la base de datos de la rama `estado`.
2. Lee los comandos que le hayas escrito al bot y los contesta.
3. Mira cuánto ha pasado desde el último barrido y decide si toca escanear:
   rápido si ha pasado más de `minutos_entre_rapidos`, completo si más de
   `horas_entre_completos`. Si no toca ninguno, no molesta a los portales.
4. Vuelve a guardar el estado.

Los intervalos están en `config.json`, separados del cron del workflow. Esa
separación es a propósito: el workflow se ejecuta a menudo para que los comandos
respondan pronto, pero los portales solo se visitan cuando de verdad hace falta.

---

## Detalles de funcionamiento

- **La primera ejecución no notifica.** Construye la línea base; si no, te
  llegarían cientos de avisos de golpe. A partir de ahí solo avisa de lo que cambia.
- **Un piso anunciado en varios portales genera un solo aviso.** Se agrupan por
  una huella aproximada (municipio + habitaciones + baños + m² + precio) y se
  prefiere la ficha de Fotocasa, que es la más completa.
- **Los cambios de precio se detectan en ambos sentidos**, subidas y bajadas, y se
  guarda el histórico completo en la tabla `price_history`.
- **Si un portal falla, los demás siguen.** El error se anota en la tabla `runs`
  y se ve con `run.py estado`.
- **Si un portal deja de devolver anuncios, te avisa.** Es el fallo más probable
  al ejecutarlo fuera de casa: los portales pueden bloquear las IP de centros de
  datos como las de GitHub, igual que ya hace Idealista. En ese caso la fuente
  dejaría de leer sin lanzar ningún error y el radar se quedaría callado
  aparentando normalidad, así que lo detecta y te lo dice por Telegram (una sola
  vez, no en cada pasada).
- **El estado vive en una rama aparte llamada `estado`**, que se reescribe entera
  en cada pasada. Si se guardara en `main`, el historial crecería con una copia
  nueva de la base de datos (600 KB) cada media hora.
- **Un anuncio solo se da por retirado si de verdad se recorrió el listado
  entero.** Si el barrido se corta por el tope de páginas o por un fallo de red,
  los que no aparecieron simplemente no se miraron. Sin esta comprobación, bajar
  el tope de páginas de Habitaclia daba de baja 346 anuncios que seguían
  publicados.
- **Habitaclia se rastrea en profundidad limitada** (4 páginas por municipio, en
  `paginas_por_municipio`). Recorrerlo entero disparaba el barrido a más de media
  hora, y es la fuente que más se solapa con Fotocasa, que sí cubre la provincia
  completa. Su cobertura es por tanto parcial y a propósito; súbelo si quieres
  más, asumiendo el coste en tiempo.

## Ficheros

```
.github/workflows/
  radar.yml          el workflow que lo mantiene vivo en GitHub
config.json          criterios de búsqueda, intervalos y fuentes
.env                 credenciales de Telegram en local (nunca se versiona)
run.py               interfaz de línea de comandos
radar/
  agent.py           orquestación de un ciclo completo
  commands.py        comandos de Telegram (/buscar, /listar...)
  occupancy.py       detección de inmuebles ocupados
  filters.py         aplicación de los criterios
  store.py           SQLite: estado, histórico de precios y diffs
  notify.py          envío por Telegram
  http.py            cliente HTTP con ritmo y reintentos
  sources/           un módulo por portal
data/radar.db        base de datos (vive en la rama `estado`)
test_occupancy.py    casos de vocabulario inmobiliario
test_parsers.py      parsers contra HTML real
```

## Mantenimiento

Los portales cambian su HTML de vez en cuando. Si dejan de llegar avisos:

```bash
.venv\Scripts\python.exe run.py probar-fuentes
```

Te dice, portal por portal, cuántos anuncios lee y cuántos con datos completos.
Si uno da 0, es que cambió el maquetado y hay que revisar su módulo en `radar/sources/`.
