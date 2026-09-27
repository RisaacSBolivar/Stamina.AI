/**
 * «Por qué esta estrategia»: qué se pudo ajustar a esta persona, y qué no.
 *
 * Va en una ruta aparte para que la página principal quede corta en la demo,
 * pero no es letra pequeña: el usuario tiene derecho a saber sobre qué se apoya
 * el plan antes de salir a correr con él.
 *
 * Lo que aquí **no** se hace es hablar en jerga. El nombre del modelo, la
 * habilidad como número y la tabla de franjas son de la investigación, y viven
 * en `docs/METODOLOGIA.md`. Lo que se enseña aquí sale de la API igual que en la
 * página principal; solo cambia el idioma, y cada idea cabe en una frase.
 */
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';

import { MedidorEvidencia } from '../../componentes/medidor-evidencia';
import { EstadoService } from '../../core/estado.service';

@Component({
  selector: 'app-detalle-page',
  imports: [RouterLink, MedidorEvidencia],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="mx-auto max-w-3xl px-4 py-6">
      <a routerLink="/estrategia" class="text-sm font-semibold underline">← Volver a la estrategia</a>

      <h1 class="mt-4 text-2xl font-bold">Por qué esta estrategia</h1>

      @if (capacidad(); as cap) {
        <!-- Cuánto se pudo ajustar, en una barra y una frase -->
        <section class="tarjeta mt-4">
          <p class="text-xs font-semibold uppercase" style="color: var(--color-tinta-suave)">
            Cuánto se ajustó a ti
          </p>
          <p class="mt-1 text-xl font-bold" style="color: var(--color-marca)">
            Personalización {{ estado.nivelPersonalizacion() }}
          </p>
          <p class="mt-1 text-sm" style="color: var(--color-tinta-media)">
            @if (cap.personalizada) {
              El plan sigue tu forma de correr, no un reparto igual del esfuerzo.
            } @else {
              Sale a ritmo constante: con pocos datos, una predicción «personalizada» sería peor
              que ninguna.
            }
          </p>
          <div class="mt-4">
            <app-medidor-evidencia [capacidad]="cap" />
          </div>
        </section>

        <!-- Qué haría falta para mejorarlo -->
        <section class="tarjeta mt-4">
          <p class="text-xs font-semibold uppercase" style="color: var(--color-tinta-suave)">
            Qué cambiaría con más historial
          </p>
          <p class="mt-2 text-sm" style="color: var(--color-tinta-media)">
            @if (!cap.regimen_fiable) {
              Nada: a esta distancia apenas hay desgaste que anticipar, y el ritmo constante ya es
              casi lo mejor que se puede hacer.
            } @else if (cap.siguiente_franja; as siguiente) {
              @if (estado.faltaPocoParaLaSiguiente()) {
                Estás justo en el borde del siguiente escalón medido.
              } @else {
                Con unas <strong>{{ estado.horas(siguiente.horas_faltantes) }}</strong> más,
                {{ cap.personalizada ? 'el ajuste se afinaría un poco más.' : 'el plan empezaría a ajustarse a ti.' }}
              }
            } @else {
              Ya estás en el tramo con más evidencia de todos los que se midieron.
            }
          </p>

          @if (estado.avisoExtrapolacion(); as aviso) {
            <div class="aviso mt-3">{{ aviso }}</div>
          }
        </section>
      } @else {
        <p class="tarjeta mt-4">
          Todavía no hay una estrategia calculada.
          <a routerLink="/estrategia" class="font-semibold underline">Vuelve al inicio</a> para empezar.
        </p>
      }

      <!-- En positivo, pero sin blanquear -->
      <section class="mt-4 grid gap-3 sm:grid-cols-3">
        <div class="tarjeta">
          <p class="text-2xl" aria-hidden="true">📈</p>
          <p class="mt-2 font-semibold">Sube todo tu historial</p>
          <p class="mt-1 text-sm" style="color: var(--color-tinta-media)">
            Es lo único que cambia el resultado.
          </p>
        </div>
        <div class="tarjeta">
          <p class="text-2xl" aria-hidden="true">🗺️</p>
          <p class="mt-2 font-semibold">Léelo como un mapa</p>
          <p class="mt-1 text-sm" style="color: var(--color-tinta-media)">
            Señala dónde sueles perder tiempo; el día de la carrera manda cómo te encuentres.
          </p>
        </div>
        <div class="tarjeta">
          <p class="text-2xl" aria-hidden="true">⌚</p>
          <p class="mt-2 font-semibold">Está probado</p>
          <p class="mt-1 text-sm" style="color: var(--color-tinta-media)">
            Validado contra carreras reales y comprobado en un reloj.
          </p>
        </div>
      </section>

      <p class="mt-4 text-xs" style="color: var(--color-tinta-suave)">
        No es consejo médico y no sustituye a un entrenador.
      </p>
    </div>
  `,
})
export class DetallePage {
  protected estado = inject(EstadoService);

  protected readonly capacidad = this.estado.capacidadEfectiva;
}
