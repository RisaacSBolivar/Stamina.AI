/**
 * La portada: el primer pantallazo de la aplicación.
 *
 * No es decoración. La página guiada arranca pidiendo archivos, y quien la abre
 * por primera vez todavía no sabe qué es esto ni qué le va a pedir. Aquí se
 * dice en dos líneas y se entra.
 *
 * Ocupa la ventana entera, sin la cabecera ni el pie de la aplicación (ver
 * `App.conArmazon`), así que el descargo de «no es consejo médico» se repite
 * aquí abajo: la regla del proyecto es que esté siempre visible, no solo cuando
 * hay una estrategia en pantalla.
 */
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { SesionService } from '../../core/sesion.service';

@Component({
  selector: 'app-bienvenida-page',
  imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="portada">
      <div class="portada-caja">
        <img src="logo-stamina.png" alt="" class="mx-auto h-28 w-auto" />

        <h1 class="mt-4 text-4xl font-bold text-white">
          Stamina<span style="color: var(--color-marca)">.AI</span>
        </h1>

        <p class="mt-3 text-base" style="color: #b8c4d6">
          Estrategia de ritmo kilómetro a kilómetro para tu carrera, a partir de tu propio
          historial.
        </p>

        <!-- Un <form> y no un botón suelto: así la tecla Enter en el campo
             entra también, que es lo que todo el mundo intenta. -->
        <form class="mt-8 text-left" (ngSubmit)="entrar()">
          <label class="etiqueta" for="nombre">¿Cómo te llamas?</label>
          <input
            id="nombre"
            class="campo"
            type="text"
            name="nombre"
            autocomplete="given-name"
            maxlength="24"
            placeholder="Tu nombre"
            [(ngModel)]="nombre"
          />
          <p class="mt-2 text-xs" style="color: #8ea3c4">
            Es opcional y solo sirve para saludarte. Se queda en esta pestaña: no se envía a
            ningún sitio ni se guarda en el servidor.
          </p>

          <button class="btn btn-primario mt-5 w-full" type="submit">
            Entrar
          </button>
        </form>

        <p class="mt-8 text-xs" style="color: #7f8da5">
          Herramienta de apoyo basada en tu propio historial. No es consejo médico ni
          sustituye a un entrenador.
        </p>
      </div>
    </div>
  `,
})
export class BienvenidaPage {
  private router = inject(Router);
  private sesion = inject(SesionService);

  protected nombre = '';

  protected entrar(): void {
    this.sesion.presentarse(this.nombre);
    void this.router.navigate(['/estrategia']);
  }
}
