import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';

import { DialogoConfirmar } from './componentes/dialogo-confirmar';
import { SesionService } from './core/sesion.service';
import { TemaService } from './core/tema.service';

/**
 * La portada se presenta sola, a pantalla completa y sin cabecera ni pie.
 *
 * Se cuenta «/» como portada porque antes de la primera navegación esa es la
 * URL que devuelve el router, y redirige aquí: sin esta línea la cabecera
 * aparecería un fotograma y desaparecería.
 */
const RUTA_PORTADA = '/bienvenida';
const esPortada = (url: string): boolean => url === '/' || url.startsWith(RUTA_PORTADA);

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, DialogoConfirmar],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (conArmazon()) {
      <header style="background: var(--color-marino)">
        <div class="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
          <a routerLink="/estrategia" class="flex shrink-0 items-center gap-2 text-white no-underline">
            <img src="logo-stamina.png" alt="" class="h-8 w-auto" />
            <span class="text-lg font-bold">Stamina<span style="color: var(--color-marca)">.AI</span></span>
            <span class="hidden text-xs sm:inline" style="color: #8ea3c4">
              estrategia de ritmo para tu carrera
            </span>
          </a>

          <div class="flex min-w-0 items-center gap-3">
            <!-- El saludo se corta con puntos suspensivos antes que empujar a la
                 marca: un nombre largo en pantalla estrecha se salía por la derecha. -->
            @if (sesion.nombre(); as nombre) {
              <span class="min-w-0 truncate text-sm text-white">
                ¡Hola, <strong>{{ nombre }}</strong>!
              </span>
            }

            <!-- Solo navega. Confirmar y borrar es cosa de la guarda de la ruta,
                 para que este boton y la flecha atras del navegador hagan lo
                 mismo sin dos implementaciones que se puedan desincronizar. -->
            <button
              type="button"
              class="btn-cabecera"
              (click)="tema.alternar()"
              [attr.aria-label]="
                tema.tema() === 'claro' ? 'Cambiar a modo oscuro' : 'Cambiar a modo claro'
              "
            >
              {{ tema.tema() === 'claro' ? 'Oscuro' : 'Claro' }}
            </button>
            <button type="button" class="btn-cabecera" (click)="salir()">Salir</button>
          </div>
        </div>
      </header>
    }

    <main>
      <router-outlet />
    </main>

    @if (conArmazon()) {
      <footer class="mx-auto max-w-5xl px-4 py-6 text-xs" style="color: var(--color-tinta-suave)">
        Herramienta de apoyo basada en tu propio historial. No es consejo médico ni sustituye a un
        entrenador.
      </footer>
    }

    <!-- Una sola instancia para toda la app: la abre ConfirmacionService. -->
    <app-dialogo-confirmar />
  `,
})
export class App {
  protected sesion = inject(SesionService);
  protected tema = inject(TemaService);
  private router = inject(Router);

  /**
   * La URL actual, como señal.
   *
   * Se mira la URL y no una bandera compartida para que recargar la página o
   * entrar por un enlace directo den el mismo resultado.
   */
  private readonly url = toSignal(
    this.router.events.pipe(
      filter((evento): evento is NavigationEnd => evento instanceof NavigationEnd),
      map((evento) => evento.urlAfterRedirects),
    ),
    { initialValue: this.router.url },
  );

  protected readonly conArmazon = computed(() => !esPortada(this.url()));

  /**
   * Volver a la portada.
   *
   * Aqui no se pregunta ni se borra nada: de eso se encarga `puedeSalir`, la
   * guarda de las rutas, que es la unica forma de cubrir tambien la flecha
   * atras del navegador.
   */
  protected salir(): void {
    void this.router.navigate(['/bienvenida']);
  }
}
