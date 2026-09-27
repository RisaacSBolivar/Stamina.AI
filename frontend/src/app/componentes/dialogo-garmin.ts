/**
 * Conexión con Garmin Connect: correo, contraseña y, si hace falta, código MFA.
 *
 * Lo que la interfaz **tiene** que decir, y dice, antes de pedir nada: que las
 * credenciales no se guardan en ningún sitio y que ninguna descarga ni subida
 * ocurre sin confirmación. No es letra pequeña: son credenciales de una cuenta
 * real de terceros y la persona tiene derecho a saber qué pasa con ellas.
 *
 * La confirmación de la descarga es un diálogo de la propia aplicación, no el
 * `confirm()` del navegador (ver `ConfirmacionService`).
 *
 * Solo se enseña donde el despliegue tiene Garmin encendido (`salud.garmin_habilitado`):
 * la sesión y la descarga necesitan estado en el servidor.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService, ErrorApi, type EstadoDescarga } from '../core/api.service';
import { ConfirmacionService } from '../core/confirmacion.service';
import { EstadoService } from '../core/estado.service';

/**
 * Cuántas horas se ofrecen descargar, además de «lo justo».
 *
 * Es un intercambio entre espera y personalización, y por eso lo elige la
 * persona: cada actividad cuesta una descarga más 0.6 s de pausa obligada contra
 * el límite de peticiones de Garmin, así que 135 h son bastantes minutos. El
 * porqué de ese 135 está en `docs/METODOLOGIA.md`.
 */
const OPCIONES_HORAS_AMPLIAS = [50, 100, 135];

/**
 * Horas brutas por cada hora que tiene que sobrevivir al control de calidad.
 *
 * Con holgura: en el historial del autor se descartaron 32 de 492 archivos.
 */
const MARGEN_CONTROL_CALIDAD = 1.3;

/**
 * Las opciones del selector. La primera es «lo justo para personalizar»: el
 * umbral que da la API (10 h en maratón, 1.8 h en carrera corta) con margen,
 * porque son horas brutas. Sin umbral no se inventa ninguno: quedan las amplias.
 */
export function opcionesHoras(umbralHoras: number | null): number[] {
  if (umbralHoras === null) return OPCIONES_HORAS_AMPLIAS;
  const justo = Math.ceil(umbralHoras * MARGEN_CONTROL_CALIDAD);
  return [justo, ...OPCIONES_HORAS_AMPLIAS.filter((horas) => horas > justo)];
}

@Component({
  selector: 'app-dialogo-garmin',
  imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="tarjeta" style="background: var(--color-marca-suave)">
      <h3 class="font-semibold">Conectar con Garmin Connect</h3>

      <p class="mt-2 text-sm" style="color: var(--color-tinta-media)">
        Trae tu historial sin exportar archivos y, al final, manda la estrategia a tu reloj.
        Es opcional.
      </p>

      <div class="aviso mt-3">
        <strong>Tus credenciales no se guardan</strong>: ni en disco, ni en base de datos, ni en
        los registros. Nada se descarga ni se sube sin que lo confirmes.
      </div>

      @if (estado.garminAutenticada()) {
        <p class="mt-3 text-sm" style="color: var(--color-ok)">
          Sesión iniciada como <strong>{{ correoEnmascarado() }}</strong
          >. Caduca en {{ minutosRestantes() }} minutos.
        </p>

        <label class="etiqueta mt-3" for="horas">Cuánto historial descargar</label>
        <select
          id="horas"
          class="campo"
          [ngModel]="horasElegidas()"
          (ngModelChange)="objetivoHoras.set(+$event)"
          [disabled]="ocupado()"
        >
          @for (opcion of opciones(); track opcion; let primera = $first) {
            <option [value]="opcion">
              {{ opcion }} horas{{ primera && estado.umbral() ? ' · lo justo para personalizar' : '' }}
            </option>
          }
        </select>
        <p class="mt-2 text-xs" style="color: var(--color-tinta-suave)">
          Más horas tardan más y ajustan mejor. Son horas brutas: el control de calidad
          descarta algunas después.
        </p>

        <div class="mt-3 flex gap-2">
          <button class="btn btn-primario" (click)="descargar()" [disabled]="ocupado()">
            {{ ocupado() ? 'Descargando…' : 'Descargar mi historial' }}
          </button>
          <button class="btn btn-secundario" (click)="cerrar()" [disabled]="ocupado()">
            Cerrar sesión
          </button>
        </div>

        @if (progreso(); as avance) {
          <div class="mt-3">
            <div class="progreso">
              <div class="progreso-relleno" [style.width.%]="avance.porcentaje"></div>
            </div>
            <p class="cifra mt-2 text-xs" style="color: var(--color-tinta-media)">
              {{ avance.actividades }} actividades · {{ avance.horas.toFixed(1) }} de
              {{ avance.objetivo_horas.toFixed(0) }} h · {{ minutos(avance.segundos) }}
            </p>
            <p class="text-xs" style="color: var(--color-tinta-suave)">
              Garmin obliga a esperar entre descargas. Puedes dejar la pestaña abierta.
            </p>

            <!-- Este no se apaga con la señal de ocupado: es el unico boton que
                 tiene sentido pulsar mientras la descarga esta en marcha. -->
            <button
              class="btn btn-secundario mt-3"
              (click)="cancelar()"
              [disabled]="cancelando()"
            >
              {{ cancelando() ? 'Cancelando…' : 'Cancelar la descarga' }}
            </button>
          </div>
        }

        @if (cancelada()) {
          <div class="aviso mt-3">
            Descarga cancelada. No se guardó nada: puedes volver a lanzarla cuando quieras.
          </div>
        }
      } @else if (pideMfa()) {
        <label class="etiqueta mt-3" for="mfa">Código de verificación</label>
        <input
          id="mfa"
          class="campo"
          [(ngModel)]="codigo"
          inputmode="numeric"
          autocomplete="one-time-code"
          placeholder="000000"
        />
        <button class="btn btn-primario mt-3" (click)="enviarMfa()" [disabled]="ocupado()">
          {{ ocupado() ? 'Comprobando…' : 'Confirmar código' }}
        </button>
      } @else {
        <label class="etiqueta mt-3" for="correo">Correo de Garmin</label>
        <input id="correo" class="campo" type="email" [(ngModel)]="correo" autocomplete="username" />

        <label class="etiqueta mt-3" for="clave">Contraseña</label>
        <input
          id="clave"
          class="campo"
          type="password"
          [(ngModel)]="contrasena"
          autocomplete="current-password"
        />

        <button class="btn btn-primario mt-3" (click)="entrar()" [disabled]="ocupado()">
          {{ ocupado() ? 'Conectando…' : 'Conectar' }}
        </button>
      }

      @if (fallo()) {
        <div class="aviso-error mt-3">{{ fallo() }}</div>
      }
    </div>
  `,
})
export class DialogoGarmin {
  private api = inject(ApiService);
  private confirmacion = inject(ConfirmacionService);
  protected estado = inject(EstadoService);

  readonly historialDescargado = output<void>();

  protected readonly opciones = computed(() => opcionesHoras(this.estado.umbral()?.horas ?? null));
  /** Lo que eligió la persona; mientras no elija, la primera opción (la más rápida). */
  protected readonly objetivoHoras = signal<number | null>(null);
  protected readonly horasElegidas = computed(() => this.objetivoHoras() ?? this.opciones()[0]);

  protected correo = '';
  protected contrasena = '';
  protected codigo = '';

  protected readonly ocupado = signal(false);
  protected readonly fallo = signal<string | null>(null);
  protected readonly pideMfa = signal(false);
  protected readonly correoEnmascarado = signal('');
  protected readonly minutosRestantes = signal(15);
  protected readonly progreso = signal<EstadoDescarga | null>(null);
  protected readonly cancelando = signal(false);
  protected readonly cancelada = signal(false);

  protected minutos(segundos: number): string {
    if (segundos < 60) return `${Math.round(segundos)} s`;
    return `${Math.floor(segundos / 60)} min ${Math.round(segundos % 60)} s`;
  }

  protected async entrar(): Promise<void> {
    if (!this.correo || !this.contrasena) {
      this.fallo.set('Hacen falta el correo y la contraseña.');
      return;
    }
    await this.intentar(async () => {
      const sesion = await this.api.loginGarmin(this.correo, this.contrasena);
      // La contraseña deja de existir en el cliente en cuanto se ha usado.
      this.contrasena = '';
      this.aplicar(sesion);
    });
  }

  protected async enviarMfa(): Promise<void> {
    const id = this.estado.sesionGarminId();
    if (!id) return;

    await this.intentar(async () => {
      const sesion = await this.api.mfaGarmin(id, this.codigo);
      this.codigo = '';
      this.aplicar(sesion);
    });
  }

  protected async descargar(): Promise<void> {
    const id = this.estado.sesionGarminId();
    if (!id) return;

    // Confirmación explícita antes de tocar la cuenta. Nunca automática.
    const seguro = await this.confirmacion.pedir({
      titulo: 'Descargar tu historial de Garmin',
      mensaje:
        `Se van a descargar hasta ${this.horasElegidas()} horas de actividades de carrera ` +
        `de tu cuenta de Garmin Connect.`,
      detalle:
        'Garmin obliga a esperar entre descargas, así que puede tardar varios minutos. Los ' +
        'archivos se procesan en memoria: el historial vuelve a tu navegador y no se ' +
        'guarda en el servidor.',
      textoConfirmar: 'Descargar',
    });
    if (!seguro) return;

    this.progreso.set(null);
    this.cancelada.set(false);
    // Mientras el historial baja, calcular una estrategia sería calcularla sin
    // él. El botón de calcular vive en la página y no aquí, así que el aviso va
    // al estado compartido en vez de a la señal local `ocupado`.
    this.estado.entradaEnCurso.set('Descargando tu historial de Garmin…');
    try {
      await this.intentar(async () => {
        const procesado = await this.api.descargarDeGarmin(id, this.horasElegidas(), (avance) =>
          this.progreso.set(avance),
        );
        // `null` es que la canceló la persona. No es un fallo y no se pinta
        // como tal: el aviso va en tono neutro, no en rojo.
        if (procesado === null) {
          this.cancelada.set(true);
          return;
        }
        await this.estado.aplicarHistorial(procesado);
        this.historialDescargado.emit();
      });
    } finally {
      // `intentar` ya se traga los errores, pero dejar el botón apagado para
      // siempre si alguna vez deja de hacerlo saldría caro.
      this.estado.entradaEnCurso.set(null);
      this.progreso.set(null);
      this.cancelando.set(false);
    }
  }

  /**
   * Parar una descarga a mitad.
   *
   * Se confirma porque puede haber quince minutos de espera detras y lo
   * bajado se descarta entero. No se espera al hilo: el bucle que consulta el
   * progreso vera el estado nuevo y cerrara solo.
   */
  protected async cancelar(): Promise<void> {
    const avance = this.progreso();
    if (!avance || this.cancelando()) return;

    const seguro = await this.confirmacion.pedir({
      titulo: '¿Cancelar la descarga?',
      mensaje:
        `Se descarta lo que lleva bajado (${avance.actividades} actividades, ` +
        `${avance.horas.toFixed(1)} h) y no se guarda nada.`,
      detalle:
        'Si lo que quieres es menos historial, cancélala y vuelve a lanzarla eligiendo ' +
        'menos horas: así el sistema sabe cuántas esperar.',
      textoConfirmar: 'Cancelar la descarga',
      textoCancelar: 'Seguir descargando',
    });
    if (!seguro) return;

    this.cancelando.set(true);
    await this.api.cancelarDescarga(avance.tarea_id).catch(() => undefined);
  }

  protected async cerrar(): Promise<void> {
    const id = this.estado.sesionGarminId();
    if (id) await this.api.cerrarGarmin(id);
    this.estado.sesionGarminId.set(null);
    this.estado.garminAutenticada.set(false);
    this.pideMfa.set(false);
  }

  private aplicar(sesion: {
    sesion_garmin_id: string;
    autenticada: boolean;
    requiere_mfa: boolean;
    correo: string;
    caduca_en_segundos: number;
  }): void {
    this.estado.sesionGarminId.set(sesion.sesion_garmin_id);
    this.estado.garminAutenticada.set(sesion.autenticada);
    this.pideMfa.set(sesion.requiere_mfa);
    this.correoEnmascarado.set(sesion.correo);
    this.minutosRestantes.set(Math.round(sesion.caduca_en_segundos / 60));
  }

  private async intentar(accion: () => Promise<void>): Promise<void> {
    this.ocupado.set(true);
    this.fallo.set(null);
    try {
      await accion();
    } catch (error) {
      this.fallo.set(
        error instanceof ErrorApi ? error.message : 'Algo salió mal hablando con Garmin.',
      );
    } finally {
      this.ocupado.set(false);
    }
  }
}
