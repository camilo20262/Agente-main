# Revisión de ejecución real - 14 de septiembre de 2026

Fuente revisada: exportación de la interfaz `WPP Media Intelligence.pdf`, con 63 páginas y diez solicitudes visibles. La revisión usa las respuestas, argumentos, resultados y gráficos incluidos en el archivo. No sustituye una repetición posterior contra el proveedor y BigQuery.

## Dictamen por solicitud

| Solicitud | Datos y alcance | Presentación | Dictamen |
|---|---|---|---|
| Compara BMW y Volvo durante 2025 | Conserva ambas marcas y el año; totales, diferencia y porcentaje son coherentes. | El PDF corta la etiqueta de Volvo. | Correcta con defecto de exportación. |
| Cinco vehículos con mayor inversión de BMW en 2025 | Devuelve cinco filas, orden y participaciones sobre el universo completo. | Las barras mayores quedan cortadas por el ancho imprimible. | Correcta en texto; gráfico ambiguo. |
| Mes de mayor inversión de BMW en 2025 | Noviembre, 489.740,95; evalúa doce meses observados. | Respuesta concisa. | Correcta. |
| Consulta el mes anterior | Recupera octubre de 2025 y mantiene BMW. | Respuesta concisa. | Correcta. |
| Qué explica el cambio | Compara octubre con septiembre y calcula contribuciones por medio. | Advierte que concentración no equivale a causalidad. | Correcta con lenguaje que debe seguir siendo descriptivo. |
| Explica la diferencia entre BMW y Volvo por medios durante 2025 | Mantiene entidades, periodo y contribuciones en el mismo periodo. | Algunas etiquetas del gráfico se cortan al imprimir. | Correcta en texto; exportación mejorable. |
| Y en 2026 | Conserva comparación y desglose; limita la evidencia al 31 de julio. | Incluye advertencia de cobertura parcial. | Correcta. |
| Solo de febrero | Conserva inicialmente BMW y Volvo, pero representa febrero como `filtros.fecha`, incompatible con el esquema. La corrección cambia después la identidad a medio y total/total. | Devuelve un parcial seguro, sin inventar cifras. | Fallo funcional. |
| Revisa Renault en 2024 con tendencias y distribución | Serie mensual y distribución por medio coherentes. | Añade un ranking diario por medio que alarga y distrae. | Datos correctos; respuesta excesiva. |
| Y en 2026 | Conserva Renault y las perspectivas; declara cobertura hasta julio. | La exportación corta junio/julio y las barras mayores. | Correcta en texto; gráfico exportado incompleto. |

## Correcciones incorporadas

1. Un intervalo emitido como `filters.fecha={start,end}` se promueve a `period` y se elimina de todos los filtros de herramientas. Si era una operación de filtro, se convierte en cambio de periodo.
2. La corrección posterior a un error de argumentos no puede cambiar la dimensión de entidad ni las entidades comparadas.
3. `ranking_segmentado_bicomp` rechaza `fecha` como grupo sin granularidad. Las tendencias temporales deben usar la serie y la distribución categórica debe ir separada.
4. Los hechos de rankings segmentados solo aparecen si el narrador los selecciona; ya no se agregan automáticamente todos al final.
5. Los gráficos muestran valores, reservan margen para etiquetas externas y desactivan el recorte de texto.
6. La hoja de impresión oculta barra lateral y entrada, usa todo el ancho disponible y evita cortar gráficos entre páginas cuando sea posible.
7. La trazabilidad empieza cerrada para evitar exposiciones accidentales y exportaciones dominadas por SQL/resultados internos.
8. Se reemplazó PyPDF2 por pypdf.
9. Las comparaciones genéricas incluyen el nombre y la unidad semánticos de la métrica.

## Verificación

`PYTHONPATH=. .venv/bin/pytest -q`: **354 pruebas aprobadas, 0 fallidas, 0 advertencias**.

Las pruebas nuevas reproducen la normalización de febrero, la conservación de BMW/Volvo, el rechazo de agrupación diaria sin granularidad y las etiquetas de gráficos. No se repitió todavía la conversación completa contra el proveedor y BigQuery después de estos cambios.

## Repetición necesaria

En la misma conversación de comparación por medios:

1. `Explica la diferencia entre BMW y Volvo por medios durante 2025.`
2. `Y en 2026.`
3. `Solo de febrero.`

El tercer turno debe ejecutar una única comparación con:

- `dimension_entidad=marca`
- `dimension=medio`
- `valor_a=BMW`
- `valor_b=Volvo`
- `fecha_inicio=2026-02-01`
- `fecha_fin=2026-02-28`
- sin `filtros.fecha`

La validación queda cerrada únicamente cuando esa repetición devuelve evidencia utilizable y el PDF nuevo muestra completos los gráficos y sus etiquetas.
