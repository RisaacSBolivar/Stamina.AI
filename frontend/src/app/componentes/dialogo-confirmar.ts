/**
 * El dialogo de confirmacion de la aplicacion.
 *
 * Usa el elemento `<dialog>` nativo con `showModal()`, que ya trae trampa de
 * foco, cierre con Escape, fondo oscurecido y apilado por encima de todo. No
 * hace falta `@angular/cdk` ni ninguna dependencia nueva.
 *
 * El foco arranca en «Cancelar» a proposito: estas confirmaciones guardan
 * operaciones contra una cuenta real de Garmin, y un Enter distraido no deberia
 * dispararlas.
 */
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterRenderEffect,
  inject,
  viewChild,
} from '@angular/core';

import { ConfirmacionService } from '../core/confirmacion.service';

@Component({
  selector: 'app-dialogo-confirmar',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <dialog
      #dialogo
      class="modal"
      aria-labelledby="modal-titulo"
      (cancel)="alCancelar($event)"
      (click)="alPulsarFondo($event)"
    >
      @if (confirmacion.peticion(); as peticion) {
        <div class="modal-caja">
          <header class="modal-marca">
            <img src="logo-stamina.png" alt="" class="h-6 w-auto" />
            <span class="text-sm font-bold">
              Stamina<span style="color: var(--color-marca)">.AI</span>
            </span>
          </header>

          <h2 id="modal-titulo" class="mt-3 text-lg font-semibold">{{ peticion.titulo }}</h2>
          <p class="mt-2 text-sm" style="color: var(--color-tinta-media)">{{ peticion.mensaje }}</p>

          @if (peticion.detalle) {
            <p class="mt-2 text-xs" style="color: var(--color-tinta-suave)">{{ peticion.detalle }}</p>
          }

          <div class="mt-5 flex flex-wrap justify-end gap-2">
            <button #cancelar class="btn btn-secundario" (click)="confirmacion.responder(false)">
              {{ peticion.textoCancelar ?? 'Cancelar' }}
            </button>
            <button class="btn btn-primario" (click)="confirmacion.responder(true)">
              {{ peticion.textoConfirmar ?? 'Continuar' }}
            </button>
          </div>
        </div>
      }
    </dialog>
  `,
})
export class DialogoConfirmar {
  protected confirmacion = inject(ConfirmacionService);

  private readonly elemento = viewChild.required<ElementRef<HTMLDialogElement>>('dialogo');
  private readonly botonCancelar = viewChild<ElementRef<HTMLButtonElement>>('cancelar');

  constructor() {
    // `afterRenderEffect` y no `effect`: el contenido del diálogo vive dentro de
    // un `@if`, así que cuando cambia la señal todavía no existe en el DOM. Con
    // un `effect` normal, `showModal()` no encuentra nada que enfocar y el foco
    // se queda en el propio <dialog> en vez de en «Cancelar».
    afterRenderEffect(() => {
      const abierto = this.confirmacion.peticion() !== null;
      const dialogo = this.elemento().nativeElement;

      if (abierto && !dialogo.open) {
        dialogo.showModal();
        this.botonCancelar()?.nativeElement.focus();
      } else if (!abierto && dialogo.open) {
        dialogo.close();
      }
    });
  }

  /** Escape. Se intercepta para que cierre por la misma via que el boton. */
  protected alCancelar(evento: Event): void {
    evento.preventDefault();
    this.confirmacion.responder(false);
  }

  /** Un clic en el fondo oscurecido llega al propio `<dialog>`, no a la caja. */
  protected alPulsarFondo(evento: MouseEvent): void {
    if (evento.target === this.elemento().nativeElement) this.confirmacion.responder(false);
  }
}
