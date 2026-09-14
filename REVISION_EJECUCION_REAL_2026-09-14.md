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

La repetición devolvió evidencia utilizable para febrero: BMW 88.994,42; Volvo 204.028,21; diferencia -115.033,79 y variación -56,38 % sobre Volvo. Quedaron confirmados el periodo, las entidades y el desglose por medio, sin `filtros.fecha`.

Esta respuesta reveló dos defectos posteriores. Las cuatro contribuciones narradas sumaban -110.972,10 y omitían un resto neto de -4.061,69, equivalente al 3,53 % de la diferencia. Además, la interpretación de TV SUSCRIPCION decía que su contribución positiva aumentaba la desventaja de BMW, cuando contablemente la compensa.

El renderer ahora conserva las cuatro contribuciones principales, calcula y muestra obligatoriamente el resto neto de las categorías omitidas y no admite interpretación cualitativa libre junto a hechos de drivers. La prueba completa posterior queda en **355 aprobadas, 0 fallidas y 0 advertencias**.

Queda pendiente verificar una nueva exportación del gráfico; la ruta funcional de febrero sí quedó comprobada con la ejecución real.

Una nueva captura reveló que el primer cierre se calculaba durante el renderizado. Aunque era aritméticamente correcto, el validador lo rechazaba porque esas cifras derivadas todavía no existían en el objeto de evidencia, por lo que la interfaz mostraba el fallback parcial. El cierre se movió a `_partition_difference`: `shown_contribution`, `residual_contribution`, sus conteos y porcentaje llegan ahora como evidencia determinística. La regresión renderiza la respuesta completa y la valida con el mismo control numérico de producción. La suite permanece en **355 aprobadas, 0 fallidas y 0 advertencias**.

## Seguimiento `solo mayo`

La trazabilidad de la ejecución confirmó que el seguimiento conservó BMW, Volvo, el desglose por medio y resolvió correctamente `2026-05-01` a `2026-05-31`. La partición de BMW devolvió cero filas y la de Volvo devolvió dos. Por tanto, el fallo actual no era de memoria ni calendario: la comparación no tenía observaciones para ambas entidades.

La respuesta anterior ocultaba ese hallazgo con el texto genérico «no obtuve evidencia utilizable», y el error del repositorio hablaba de «ambos periodos» aunque se comparaban entidades. Ahora el resultado conserva una observación estructurada por entidad, comunica cuál no tiene filas, muestra el total de la entidad que sí tiene datos y omite diferencia y drivers. La ausencia de filas no se convierte en inversión cero.

La primera ejecución idéntica había terminado antes de crear una consulta, pero su diagnóstico quedó irrecuperable porque la interfaz solo mostraba debug cuando había evidencia y reutilizaba las métricas del último turno. Las métricas y el plan quedan ahora almacenados por mensaje, y el panel debug aparece también en fallos previos a la consulta. Así, una repetición futura permitirá distinguir un rechazo del plan, un fallo del proveedor y un resultado sin filas.

Verificación posterior: **356 pruebas aprobadas, 0 fallidas y 0 advertencias**.

## Presentación para clientes

La revisión visual mostró que las respuestas seguían exponiendo hechos correctos con una redacción demasiado cercana al resultado de consulta: fechas ISO, pares `dimensión=valor`, repetición del alcance y limitaciones formuladas como detalles del sistema. La capa factual se reescribió para conservar exactamente las mismas cifras con una voz ejecutiva, periodos naturales en español y contexto integrado en oraciones de negocio.

Las respuestas completas se organizan ahora en lectura ejecutiva, hallazgos clave, hipótesis de trabajo y consideraciones del análisis. Los medios que amplían una brecha se distinguen de los que la compensan. Las salidas parciales explican qué información sí está disponible, su implicación y el siguiente paso recomendado, sin mencionar BigQuery, SQL, JSON, herramientas, filas o validadores.

El cambio mantiene el control numérico: porcentajes negativos pueden expresarse como magnitudes «por debajo» o «compensó» solo cuando la evidencia contiene el valor firmado correspondiente. La regresión incluye una comparación de clientes completa y el caso de una entidad sin observaciones. Verificación final: **357 pruebas aprobadas, 0 fallidas y 0 advertencias**.
