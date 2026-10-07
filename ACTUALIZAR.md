# Actualizar el bot que ya tienes funcionando

Esta versión añade la **consola Nintendo Switch 2 — Zelda 40.º aniversario**, anunciada para el 29 de octubre de 2026. No incluye el juego Ocarina of Time suelto ni la Switch OLED de Zelda, ni mandos o fundas.

## Pasos en macOS

1. Descarga el ZIP actualizado y descomprímelo en **Descargas**, en una carpeta diferente de la instalación actual. No reemplaces la carpeta instalada desde Finder.
2. Ejecuta:

```bash
python3 "$HOME/Downloads/ps5-price-bot/scripts/update_macos.py" "/ruta/al/ps5-price-bot"
```

Sustituye la segunda ruta por la ubicación de la instalación que ya estás usando. Si Finder añade ` 2` al nombre de la carpeta descargada, ajusta solo la primera ruta.

El actualizador detiene el servicio, guarda una copia de los archivos que sustituye en `backups/`, añade las búsquedas de Switch 2 y reinicia el mismo servicio. **No copia ni sobrescribe `.env`, `data/` ni `logs/`**. Se conserva el token, el chat y los precios registrados. Mantiene tus URLs, intervalos y fuentes de PS5 desactivadas; los proveedores desactivados se mantienen desactivados en Switch 2. Si falla antes de completar la actualización, restaura los archivos sustituidos.

No hace falta crear otro bot ni ejecutar de nuevo BotFather.

## Comandos

| Comando | Qué consulta |
|---|---|
| `/ps5` | Las cuatro PS5. |
| `/switch2` o `/zelda` | La consola Switch 2 Zelda 40.º aniversario. |
| `/estado` | Todos los monitores. |
| `/estado_ps5` | Solo PS5. |
| `/estado_switch2` | Solo Switch 2 Zelda. |
| `/chollos` | Anuncios PS5. |
| `/chollos_switch2` | Anuncios de la consola Switch 2 Zelda. |

Ambas familias emplean Amazon, Fnac, MediaMarkt, PcComponentes, Idealo y Chollometro, con su propio estado de lectura. Un fallo al buscar Switch 2 no invalida la lectura de PS5 de la misma tienda. El intervalo sigue siendo 30 segundos; los bloqueos provocan pausas progresivas.

Antes del lanzamiento, una ficha que anuncie disponibilidad para esta edición se presenta como **preventa/reserva**; confirma la fecha de entrega. Las fichas con disponibilidad desconocida se etiquetan como tales. Se avisa si una ficha agotada pasa a permitir reserva, aunque no cambie el precio.

## Los errores que has observado

- **Fnac e Idealo, HTTP 403:** la web rechaza la petición desde esa conexión. Esta actualización no garantiza eliminar el bloqueo ni lo sortea. El bot continúa con las demás fuentes y reintenta con pausas.
- **Amazon, cero fichas:** que la web responda no demuestra que se estén vigilando consolas. Ahora aparecerá **🟡 Sin coincidencias válidas**, y no un ✅. Se amplía la lectura de títulos y precios y se incorpora diagnóstico para ver qué se descarta. La causa exacta en tu Mac sigue pendiente de ese diagnóstico.
- **Fat sin precio:** no significa que no exista a la venta; no se ha obtenido una ficha válida reciente de las fuentes accesibles.

Si Amazon sigue sin detectar consolas, ejecuta este diagnóstico de solo lectura y comparte su salida:

```bash
cd "/ruta/al/ps5-price-bot"
.venv/bin/python -m ps5bot.app --check --source Amazon --diagnose
```

Solo muestra títulos, precios públicos y el resultado del filtro; no imprime el token ni el HTML completo. Se puede ejecutar mientras el servicio está activo porque no recibe mensajes de Telegram ni modifica el historial.

Para comprobar la búsqueda nueva:

```bash
.venv/bin/python -m ps5bot.app --check --source "PcComponentes · Switch 2 Zelda"
```

En las búsquedas sin una consola válida se muestra «sin precio reciente disponible». No se utiliza el precio del juego o de un accesorio como si fuera la consola.

Referencia oficial: [Nintendo Switch 2 — Packs](https://www.nintendo.com/es-es/Hardware/Nintendo-Switch-2/Packs-de-Nintendo-Switch-2-/Nintendo-Switch-2-Packs-2785628.html).


La actualización conserva `data/prices.sqlite3`. Las tablas nuevas de deduplicación de avisos y `/logs` se crean automáticamente al primer arranque; no borres `data/`.
