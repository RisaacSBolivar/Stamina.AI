/**
 * Cuánto historial tienes frente al siguiente escalón medido, en una barra.
 *
 * Sustituye al párrafo de «te faltan 3.9 h»: la misma información se lee de un
 * vistazo. Las marcas son las franjas de la curva de capacidad que
 * personalizan, tal como las devuelve la API; ninguna cifra está escrita aquí.
 */
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import type { Capacidad } from '../core/api.service';
import { medidor } from '../core/relato';

@Component({
  selector: 'app-medidor-evidencia',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (datos(); as m) {
      <div class="medidor" role="img" [attr.aria-label]="texto()">
        <div class="flex items-baseline justify-between gap-3 text-sm">
          <span>
            <span class="cifra text-lg font-bold" style="color: var(--color-marca)">
              {{ horas(m.horas) }}
            </span>
            <span style="color: var(--color-tinta-media)"> de historial</span>
          </span>
          <span class="text-right text-xs" style="color: var(--color-tinta-media)">
            {{ texto() }}
          </span>
        </div>

        <div class="medidor-pista">
          <div
            class="medidor-relleno"
            [class.medidor-relleno--ok]="m.personalizada"
            [style.width.%]="(100 * m.horas) / m.escala"
          ></div>
          @for (marca of m.marcas; track marca) {
            <span class="medidor-marca" [style.left.%]="(100 * marca) / m.escala"></span>
            <span class="medidor-etiqueta cifra" [style.left.%]="(100 * marca) / m.escala">
              {{ horas(marca) }}
            </span>
          }
        </div>
      </div>
    } @else if (capacidad(); as cap) {
      <p class="text-sm" style="color: var(--color-tinta-media)">
        A {{ cap.km_objetivo.toFixed(1) }} km, más horas de historial no cambian el resultado.
      </p>
    }
  `,
})
export class MedidorEvidencia {
  readonly capacidad = input.required<Capacidad>();

  protected readonly datos = computed(() => medidor(this.capacidad()));

  protected readonly texto = computed(() => {
    const m = this.datos();
    if (!m) return '';
    if (m.enElBorde) return 'justo en el borde del siguiente escalón';
    if (!m.personalizada) return `personaliza desde ${this.horas(m.meta)}`;
    if (m.meta > m.horas) return `siguiente escalón: ${this.horas(m.meta)}`;
    return 'en el tramo con más evidencia medida';
  });

  protected horas(valor: number): string {
    return valor < 1 ? `${Math.round(valor * 60)} min` : `${valor.toFixed(1)} h`;
  }
}
