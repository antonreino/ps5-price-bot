# Bot de precios PS5 + Switch 2 Zelda · Telegram

Proyecto Python para vigilar PS5 Fat y Slim, digitales y con lector, excluyendo PS5 Pro, y la consola **Nintendo Switch 2 — Zelda 40.º aniversario**. Envía avisos por Telegram y responde a `/ps5` y `/switch2`. Preparado para ejecutarse en tu Mac mediante launchd; también funciona en Linux.

**Si ya instalaste la versión PS5, sigue `ACTUALIZAR.md`: conserva el mismo bot, token, chat e historial.** Para una instalación nueva, sigue los pasos de abajo. Las fuentes son páginas públicas: la lectura puede fallar por bloqueo o cambios de formato. Consulta `VALIDACION.md` para distinguir las integraciones probadas de las pendientes. No incorpora precios inventados ni APIs privadas supuestas.

## Instalación en tu Mac

1. Descomprime el ZIP y coloca la carpeta `ps5-price-bot` en una ubicación permanente de tu elección.
2. Necesitas **Python 3.10 o superior**, con `pip` y `venv`. Compruébalo con `python3 --version`.
3. En Terminal:

```bash
cd "/ruta/a/ps5-price-bot"
bash scripts/install-macos.sh
```

Sustituye `/ruta/a/ps5-price-bot` por la ruta donde hayas colocado la carpeta.

El instalador crea un entorno virtual, instala las dependencias y abre el asistente:

- Crea un **bot nuevo** en [@BotFather](https://t.me/BotFather), enviando `/newbot`.
- Pega el token en Terminal cuando lo pida; no se muestra al escribir ni debes pegarlo en esta conversación.
- El asistente te dará el enlace a tu nuevo bot y un mensaje `/start CÓDIGO`. Envíalo en privado a ese bot.
- Se guarda `.env` con permisos restringidos y se instala el servicio de inicio de macOS.

Utiliza un token exclusivo: dos programas leyendo el mismo bot por `getUpdates` se interferirían. El asistente no cambia ni elimina un webhook existente. Este proyecto es independiente de tus otros bots.

Al arrancar recibirás un aviso de inicio. Envía `/estado` para comprobar cada fuente y `/ps5` después de la primera lectura. **Un aviso de inicio no significa que todas las tiendas funcionen.**

El servicio arranca al iniciar sesión y se reinicia si falla. El Mac debe permanecer encendido, con conexión y sin suspensión; la carpeta del proyecto debe estar accesible. Si está en un SSD externo, este debe estar montado. El instalador no cambia los ajustes de energía.

## Comandos de Telegram

| Comando | Respuesta |
|---|---|
| `/ps5` | Mejor precio reciente encontrado de cada uno de los cuatro modelos, con enlace, fuente y condiciones conocidas. |
| `/switch2` o `/zelda` | Mejor precio de la consola Switch 2 Zelda 40.º aniversario. No incluye el juego suelto ni otros modelos de Switch. |
| `/estado` | Resultado de cada fuente, hora de consulta y próxima comprobación. |
| `/estado_ps5` / `/estado_switch2` | Estado de las fuentes de una sola familia. |
| `/chollos` | Anuncios leídos recientemente de Chollometro, pendientes de confirmar en la tienda. |
| `/chollos_switch2` | Anuncios de Chollometro de la consola especial de Switch 2. |
| `/ayuda` | Lista de comandos. |

Las cuatro líneas principales de `/ps5` siguen este formato (importes solo ilustrativos):

```text
PS5 Edición Digital (Fat): 549 € · Comprar (tienda)
PS5 Con disco (Fat): 649 € · Comprar (tienda)
PS5 Slim Digital: 450 € · Comprar (tienda)
PS5 Slim lector: 550 € · Comprar (tienda)
```

Cada precio incluye el título de la ficha, la hora de lectura y la información disponible de stock/envío. Si procede de Idealo, aparece **«desde»** y el enlace **«Comparar ofertas»**, porque el comparador no es la tienda que vende. Si no hay datos recientes, indica «sin precio reciente disponible».

## Qué se comprueba y cuándo avisa

- La cadencia es **específica por proveedor**: Chollometro 90 s, MediaMarkt 5 min, Fnac y PcComponentes 10 min, Amazon e Idealo 15 min. Las fuentes PS5/Switch 2 se escalonan al arrancar y las peticiones al mismo dominio se serializan con una separación mínima para reducir 403/429.
- Las URLs compartidas, como el RSS de Chollometro, usan una caché corta en memoria para que PS5 y Switch 2 puedan reutilizar una sola descarga en vez de pedir el mismo recurso dos veces.
- Amazon, Fnac, MediaMarkt, PcComponentes, Idealo y Chollometro están configuradas en `config.json`. Chollometro combina su RSS de nuevos anuncios con las categorías de PS5 y PS5 Slim.
- Switch 2 usa las mismas seis plataformas en monitores separados. Sus anuncios de Chollometro se buscan en el RSS de nuevos anuncios. Un fallo de la búsqueda de una consola no invalida los datos de la otra.
- La primera lectura correcta establece la referencia, sin enviar todos los productos como nuevas ofertas. Las posteriores notifican **cualquier variación de al menos un céntimo**, tanto subida como bajada, de cada ficha/vendedor detectado. No se limita a la oferta más barata.
- También avisa al aparecer una ficha nueva y al volver un stock que estaba explícitamente agotado.
- La edición Switch 2 Zelda se lanza el 29/10/2026. Antes de esa fecha, las fichas que indiquen disponibilidad se etiquetan como preventa/reserva; también avisa cuando una ficha agotada permite reservar al mismo precio.
- La identidad de las fichas, los precios, el estado y las notificaciones pendientes se conservan en SQLite. Reiniciar no provoca repetir todos los avisos de precio.
- Una fuente que falla no escribe precios vacíos ni ceros. Avisa de la incidencia y, después, de la recuperación.
- Ante errores hace una pausa progresiva; ante 403/CAPTCHA, al menos cinco minutos. Respeta `Retry-After`. **No se puede garantizar una consulta exitosa cada 30 segundos**, ni detectar cambios ocurridos entre dos lecturas o todavía no publicados por la fuente.
- `/ps5` consulta el último resultado guardado; no dispara seis peticiones nuevas por cada mensaje. Solo muestra lecturas de los últimos 180 segundos y de fuentes cuyo último resultado fue correcto.
- Las ofertas agotadas y los anuncios de Chollometro no se mezclan con precios de compra actuales. Los anuncios tienen sus propias alertas y `/chollos`.

Las notificaciones usan una cola persistente con reintentos. Si Telegram acepta un mensaje pero se pierde su respuesta, un reintento podría duplicar ese mensaje: la entrega no promete «exactamente una vez».

### Fuentes temporalmente desactivadas

Amazon, Fnac e Idealo quedan desactivados por defecto mientras sus respuestas no sean fiables desde esta conexión: Amazon devuelve listados sin precio y bloquea las fichas directas con CAPTCHA; Fnac e Idealo responden con HTTP 403. Se conservan en `config.json` con `enabled: false` para poder reactivarlos cuando vuelva a existir una vía de lectura estable.

### Estrategia de consultas

El bot prioriza rapidez útil frente a frecuencia bruta. Consultar una tienda cada 30 segundos no garantiza detectar antes una oferta si el proveedor empieza a responder con 403/429. Por eso:

- Chollometro/RSS se consulta con mayor frecuencia, porque sirve como canal rápido de descubrimiento.
- Las tiendas se consultan con una cadencia menor y escalonada.
- PS5 y Switch 2 nunca deben golpear simultáneamente el mismo dominio.
- Las páginas de producto/categoría específicas se prefieren a búsquedas genéricas cuando están verificadas.
- Una URL individual puede fallar sin invalidar las demás URLs de la misma fuente; la fuente solo pasa a error si fallan todas.
- La PS5 Slim Digital de PcComponentes se vigila además mediante su ficha directa, de forma independiente, para detectar su vuelta a stock aunque no aparezca en la categoría.
- Un 403/429 mantiene el backoff existente y no sustituye el último precio válido.

## Alcance de la búsqueda y de los precios

Se leen las páginas configuradas de búsqueda/categoría, con las fichas que publican en esa respuesta. **No se recorre todo el catálogo ni todas las páginas de resultados**. Puedes añadir fichas concretas o páginas adicionales a `urls`. Las páginas adicionales de una misma fuente se leen en serie; si tardan más de 30 segundos, la siguiente ejecución empieza al terminar. Una fuente con varias URLs solo publica el conjunto si todas se han leído correctamente.

Se prioriza identificar bien la consola: una PS5 sin generación explícita no se considera Fat por defecto. Se reconocen Slim, chasis A–E y referencias CFI compatibles. Las fichas originales de Idealo identificadas durante la preparación tienen asignación explícita en `model_overrides`. Un título ambiguo se descarta; las Pro se excluyen incluso con una asignación manual.

Por defecto se excluyen reacondicionadas y usadas cuando el título o los datos estructurados lo indican. Puede haber fichas con condición desconocida; no se presentan como nuevas verificadas. Se admiten packs y vendedores de marketplace y se muestra el título para no esconder qué incluye la oferta. El parser no puede certificar una ficha mal etiquetada por la tienda.

El mínimo se calcula por **precio publicado del artículo**, sin añadir envío. No se aplican cupones, descuentos personales, ventajas Prime/socio, financiación, reembolsos ni condiciones de pago. Cuando el envío o stock se desconocen se indica expresamente. Los precios «desde» de Idealo pueden agrupar variantes: confirma la opción exacta, el vendedor y las condiciones antes de comprar.

## Diagnóstico y mantenimiento

Comprobar las seis fuentes una vez, **sin Telegram ni modificar el historial**:

```bash
.venv/bin/python -m ps5bot.app --check
```

Devuelve código 0 si las fuentes se pueden interpretar, 2 si alguna falla. Cero fichas identificadas puede ser un resultado válido de una página de productos que no contiene consolas clasificables, pero se marca en amarillo como **sin coincidencias válidas**, no como una fuente con precios vigilados. Un cambio de diseño sin fichas reconocibles se informa como error.

Para diagnosticar Amazon sin imprimir credenciales ni HTML completo:

```bash
.venv/bin/python -m ps5bot.app --check --source Amazon --diagnose
```

Ver logs, reiniciar tras editar la configuración o consultar el servicio:

```bash
tail -n 80 logs/bot.log
.venv/bin/python scripts/launch_agent.py restart
.venv/bin/python scripts/launch_agent.py status
```

Quitar el servicio manteniendo los datos:

```bash
.venv/bin/python scripts/launch_agent.py uninstall
```

Si la fuente devuelve 403/503/CAPTCHA o requiere JavaScript, el adaptador HTTP no puede leerla. No lleva proxies, soluciones de CAPTCHA ni métodos para eludir controles. Las alternativas son una integración autorizada de esa fuente o actualizar el adaptador cuando vuelva a permitir la lectura. Que tu navegador abra una página no garantiza que la petición del bot funcione.

## Configuración

`config.json` contiene:

- `interval_seconds`: 30 por defecto; mínimo 30.
- `timeout_seconds`: 18 por petición; máximo 25.
- `stale_after_seconds`: 1800; evita que fuentes con cadencias de 10–15 minutos desaparezcan entre dos consultas correctas. Una fuente marcada como error sigue excluyéndose inmediatamente.
- `include_used`: `false`; cambia a `true` si quieres permitir fichas marcadas como usadas.
- `sources[].enabled`: activa o desactiva cada fuente.
- `sources[].family`: `ps5` o `switch2`; separa los filtros, comandos y estados. Las configuraciones antiguas sin este campo se interpretan como PS5.
- `sources[].urls`: búsquedas/categorías/fichas concretas HTTPS del dominio correspondiente.
- `model_overrides`: asignación explícita de URL canónica a `fat_digital`, `fat_disc`, `slim_digital` o `slim_disc`; úsala solo tras identificar la ficha.

En `.env`, `TELEGRAM_CHAT_IDS` permite varios identificadores separados por comas. Solo esos chats reciben respuestas y avisos. Si autorizas un grupo, cualquier miembro que escriba en él puede consultar los precios. No hay comandos para ejecutar shell ni cambiar la configuración por Telegram.

## Ejecución manual / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/configure.py
.venv/bin/python -m ps5bot.app
```

No ejecutes el modo manual a la vez que el servicio. En Linux puedes mantener este proceso con tu gestor de servicios habitual; el instalador incluido solo configura launchd en macOS. Las horas de los mensajes se muestran en Europe/Madrid.

## Desarrollo y pruebas

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Los 37 tests cubren formatos de precios, modelos, Pro/accesorios, HTML real reducido de las fuentes accesibles, agotados, antigüedad, fallos, reinicios, cambios de un céntimo, cambios de ofertas no mínimas, autorización y cola de Telegram. También cubren la edición Zelda, reservas, separación de familias, diagnóstico de Amazon y actualización conservando la configuración. Amazon y Fnac tienen fixtures sintéticas, que verifican la lógica pero no demuestran compatibilidad con su web actual.

Los archivos `.env`, `data/`, `logs/` y `.venv/` están excluidos de git. No subas el token. Las dependencias quedan fijadas en `requirements.txt`.

Referencias de implementación: [Telegram Bot API](https://core.telegram.org/bots/api), [FAQ de bots](https://core.telegram.org/bots/faq), [Schema.org Product](https://schema.org/Product) y las páginas públicas enumeradas en `config.json`.

## Amazon y bloqueos anti-bot

Amazon puede responder a consultas automatizadas con una página de bloqueo (por ejemplo, `Lo sentimos.` o avisos sobre `acceso automatizado`) aunque la web funcione normalmente en un navegador. El bot detecta estas respuestas como `Página de bloqueo/CAPTCHA`, conserva el último precio válido y aplica backoff en lugar de interpretar el bloqueo como cero productos.

El adaptador HTML de Amazon se mantiene para respuestas válidas y pruebas, pero para monitorización estable no se recomienda intentar eludir el bloqueo. Si Amazon bloquea la consulta, el resto de fuentes continúan funcionando y `/estado` refleja la incidencia. Idealo y Chollometro pueden seguir aportando ofertas cuyo vendedor sea Amazon cuando dichas páginas las publiquen.



## Notificaciones y diagnóstico

El chat de Telegram solo recibe avisos de productos/ofertas, cambios de precio y cambios de stock relevantes. Los errores HTTP, bloqueos, recuperaciones de fuentes y otros eventos técnicos no se publican automáticamente. Consúltalos con `/logs`; `/estado` muestra el estado actual y la próxima revisión de cada fuente.

Los avisos enviados se registran de forma persistente en SQLite (`published_notifications`) para que el mismo aviso exacto no vuelva a publicarse tras reinicios. Amazon usa una cadencia de 15 minutos y PcComponentes de 5 minutos; sus fuentes PS5/Switch 2 se escalonan al arrancar para reducir 403/429.

### Carrefour Switch 2 Zelda

`Carrefour · Switch 2 Zelda` queda **desactivada temporalmente**. La URL de producto pública puede abrirse en navegador, pero la respuesta HTTP recibida por el bot devuelve la categoría general de consolas (sin Zelda, sin 519 € y sin EAN de la edición), por lo que mantenerla activa podría producir falsos positivos. Carrefour sigue activo para PS5.
