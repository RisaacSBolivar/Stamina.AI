/**
 * Arriba del resultado: una frase que cuente la carrera y tres cifras grandes.
 *
 * Es lo primero que se lee, así que lleva lo que hay que llevarse a la salida:
 * a qué ritmo arrancar y dónde está lo duro. La frase y las cifras salen de la
 * estrategia que devolvió la API (ver `core/relato.ts`).
 */
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import type { Estrategia } from '../core/api.service';
import { cifras, titular } from '../core/relato';

@Component({
  selector: 'app-resumen-carrera',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <p class="titular">{{ frase() }}</p>

    <div class="mt-4 grid grid-cols-3 gap-3">
      <div class="cifra-grande">
        <p class="cifra">{{ numeros().tiempo }}</p>
        <p class="cifra-grande-etiqueta">tiempo</p>
      </div>
      <div class="cifra-grande">
        <p class="cifra">{{ numeros().ritmoMedio }}<span class="unidad"> /km</span></p>
        <p class="cifra-grande-etiqueta">ritmo medio</p>
      </div>
      @if (numeros().kmExigente; as km) {
        <div class="cifra-grande">
          <p class="cifra">km {{ km.km }}</p>
          <p class="cifra-grande-etiqueta">
            el más exigente · {{ km.pendiente > 0 ? '+' : '' }}{{ km.pendiente.toFixed(1) }} %
          </p>
        </div>
      }
    </div>
  `,
})
export class ResumenCarrera {
  readonly estrategia = input.required<Estrategia>();

  protected readonly frase = computed(() => {
    const e = this.estrategia();
    return titular(e.entrenamiento.pasos, e.capacidad.personalizada);
  });

  protected readonly numeros = computed(() => {
    const e = this.estrategia();
    return cifras(e.tabla_km, e.indicadores.tiempo_estimado_h, e.ruta.km_totales);
  });
}
