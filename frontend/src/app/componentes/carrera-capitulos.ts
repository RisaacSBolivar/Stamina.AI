/**
 * La carrera por capítulos: los tramos del entrenamiento en una sola barra.
 *
 * Cada capítulo es un paso del `.FIT` —lo que el reloj irá marcando—, con su
 * ancho proporcional a los km y el color de su zona. Cuenta la carrera como una
 * historia (salida, lo duro, el final) y es, literalmente, lo que verá el
 * corredor en la muñeca.
 */
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import type { PasoEntrenamiento } from '../core/api.service';
import { rangoRitmo, ritmo } from '../core/formato';
import { colorDe } from '../core/zonas';

/**
 * Por debajo de este ancho, el texto no cabe y se queda en el tooltip. En la
 * barra va el ritmo central y no el rango: cabe en tramos de 3 km, que suelen
 * ser justo los exigentes, los que el titular manda mirar.
 */
const PCT_MINIMO_PARA_TEXTO = 6;

@Component({
  selector: 'app-carrera-capitulos',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="capitulos" role="list" aria-label="Los tramos del entrenamiento">
      @for (c of capitulos(); track c.paso.km_inicio) {
        <div
          class="capitulo"
          role="listitem"
          [style.flex-grow]="c.paso.km"
          [style.background]="c.color"
          [attr.title]="c.titulo"
          [attr.aria-label]="c.titulo"
        >
          @if (c.conTexto) {
            <span class="capitulo-km cifra">{{ c.paso.km_inicio }}–{{ c.paso.km_fin }}</span>
            <span class="capitulo-ritmo cifra">{{ c.central }}</span>
          }
        </div>
      }
    </div>
    <div class="mt-1 flex justify-between text-xs cifra" style="color: var(--color-tinta-suave)">
      <span>km 0</span>
      <span>km {{ total() }}</span>
    </div>
  `,
})
export class CarreraCapitulos {
  readonly pasos = input.required<PasoEntrenamiento[]>();

  protected readonly total = computed(() => this.pasos().at(-1)?.km_fin ?? 0);

  protected readonly capitulos = computed(() => {
    const total = this.total() || 1;
    return this.pasos().map((paso) => {
      const rango = rangoRitmo(paso.ritmo_min, paso.ritmo_max);
      return {
        paso,
        central: ritmo((paso.ritmo_min + paso.ritmo_max) / 2),
        color: colorDe(paso.zona),
        conTexto: (100 * paso.km) / total >= PCT_MINIMO_PARA_TEXTO,
        titulo: `Km ${paso.km_inicio} a ${paso.km_fin} · ${paso.zona} · ${rango} /km`,
      };
    });
  });
}
