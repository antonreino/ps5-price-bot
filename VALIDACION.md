# Validación · 5 de octubre de 2026

## Actualización PS5 + Switch 2 Zelda

**36 tests correctos** en Linux. La versión original ya fue instalada por el usuario y respondió en Telegram; la actualización aún debe instalarse en su Mac. No se ha utilizado un token real desde este entorno.

Se ha verificado el nombre oficial de la consola en [Nintendo España](https://www.nintendo.com/es-es/Hardware/Nintendo-Switch-2/Packs-de-Nintendo-Switch-2-/Nintendo-Switch-2-Packs-2785628.html): Nintendo Switch 2 (edición 40.º aniversario de The Legend of Zelda), con lanzamiento el 29/10/2026.

Lecturas directas de la búsqueda nueva durante la preparación:

- PcComponentes: ficha de la consola identificada; se etiqueta como reserva antes del lanzamiento.
- Idealo: ficha de la consola identificada; precio «desde», condiciones pendientes de la tienda final. Esto no resuelve el HTTP 403 observado en la conexión del usuario.
- MediaMarkt: página leída, pero sin una consola de esa edición entre las fichas recibidas; descartados el juego Ocarina of Time, el mando de aniversario, accesorios y otras Switch.
- Fnac: HTTP 403, sin posibilidad de validar la lectura desde aquí.
- Amazon: la consulta PS5 devuelve HTTP 503 en este entorno. La causa de las cero fichas en el Mac del usuario sigue pendiente del diagnóstico local. Se amplían títulos y precios compatibles, sin dar por resuelto el acceso.
- Chollometro: la nueva búsqueda usa el RSS público existente; la ausencia de anuncios coincidentes no se interpreta como un precio disponible.

Se añaden 11 pruebas a las 25 originales: consola frente a juego/accesorios, reservas, fixtures reales de Switch 2, títulos y precios Amazon, diagnósticos, RSS compartido filtrado por familia, comandos separados, estado amarillo con cero fichas, aviso al abrir reservas y migración idempotente que conserva ajustes. La selección de archivos del actualizador excluye credenciales, historial y logs.

El instalador/actualizador macOS no se ha ejecutado en macOS durante esta preparación. Se ha comprobado su sintaxis y probado la fusión de configuraciones; la actualización real y el envío Telegram quedan pendientes de su ejecución local.

## Validación original de PS5 (referencia)

## Fuentes consultadas en directo

| Fuente | Resultado observado | Qué queda por comprobar |
|---|---|---|
| Amazon | HTTP 503 en la búsqueda configurada | Acceso y compatibilidad del adaptador desde tu conexión. Solo fixture sintética. |
| Fnac | HTTP 403 en categoría y ficha consultadas | Acceso y compatibilidad del adaptador desde tu conexión. Solo fixture sintética. |
| MediaMarkt | Búsqueda accesible; 6 fichas Slim clasificadas | Estabilidad continuada; los datos recibidos no confirman stock. |
| PcComponentes | Categoría accesible; 4 fichas Slim clasificadas, con stock estructurado | Estabilidad continuada y cobertura de otras páginas. |
| Idealo | Búsqueda accesible; 27 fichas clasificadas, cubriendo las cuatro variantes | Precio final, envío y stock de la tienda a la que remite el comparador. |
| Chollometro | RSS `/rss/nuevos` y categorías `/categorias/ps5` y `/categorias/ps5-slim` accesibles | Vigencia real de cada oferta en la tienda. Una ficha activa clasificada con la referencia «E Chassis»; anuncios caducados excluidos. |

Las primeras consultas a algunas páginas recibieron bloqueos. Se corrigió la URL inicial de grupo de Chollometro utilizando las categorías y el RSS enlazados en su propia web. La tabla refleja las últimas comprobaciones, no garantiza disponibilidad futura. No se han sorteado controles de acceso.

## Pruebas automáticas

25 tests correctos con `python -m unittest discover -s tests -v`:

- Clasificación de los cuatro modelos; exclusión de Pro, accesorios, productos usados y títulos ambiguos.
- Formatos europeos de precio; rechazo de cuotas, texto ambiguo y valores inválidos.
- Fixtures reales reducidas de MediaMarkt, PcComponentes, Idealo y Chollometro.
- Fixtures sintéticas de los adaptadores de Amazon y Fnac y del RSS de Chollometro.
- Extracción del precio explícito del RSS sin confundirlo con el PVP anterior.
- Primera lectura, subidas/bajadas de un céntimo, ofertas que no son el mínimo, persistencia tras reinicio.
- Errores que no sustituyen precios, avisos de incidencia sin repetición continua, agotados, fichas desaparecidas y datos caducados.
- Chats autorizados, comandos dirigidos a otro bot, parámetros de Telegram y cola persistente con reintentos.

La creación de mensajes Telegram se prueba con un transporte simulado; **no se ha enviado un mensaje real**. La sintaxis Python y del instalador se ha comprobado; **launchd requiere la prueba de instalación en macOS**. No se ha realizado una prueba de funcionamiento prolongada.

## Comprobación pendiente en tu Mac

Después de instalar, ejecuta:

```bash
.venv/bin/python -m ps5bot.app --check
```

Después consulta `/estado` en el bot. Si Amazon o Fnac siguen fallando, esas fuentes no estarán monitorizando precios aunque el resto funcione. Sus adaptadores necesitarán una vía de acceso permitida y comprobar el HTML recibido. No des por operativo el conjunto de seis fuentes hasta resolverlo.
