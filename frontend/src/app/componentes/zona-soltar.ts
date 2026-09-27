/**
 * Zona de arrastrar y soltar archivos.
 *
 * Sirve para el historial (.FIT, varios) y para la ruta (.GPX, uno). Acepta
 * también el clic de toda la vida, porque arrastrar no funciona igual en todos
 * los navegadores ni con teclado.
 */
import { ChangeDetectionStrategy, Component, input, output, signal } from '@angular/core';

@Component({
  selector: 'app-zona-soltar',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="soltar"
      [class.soltar--activo]="encima() && !esperando()"
      [class.soltar--apagada]="esperando()"
      (dragover)="alArrastrar($event)"
      (dragleave)="encima.set(false)"
      (drop)="alSoltar($event)"
      (click)="abrir(entrada)"
      (keydown.enter)="abrir(entrada)"
      (keydown.space)="abrir(entrada)"
      [attr.tabindex]="esperando() ? -1 : 0"
      [attr.aria-disabled]="esperando() !== null"
      role="button"
      [attr.aria-label]="etiqueta()"
    >
      <p class="font-semibold" style="color: var(--color-tinta)">{{ etiqueta() }}</p>
      <p class="mt-1 text-sm" style="color: var(--color-tinta-suave)">
        {{ esperando() ?? ayuda() }}
      </p>

      <input
        #entrada
        type="file"
        class="hidden"
        [accept]="acepta()"
        [multiple]="multiple()"
        (change)="alElegir($event)"
      />
    </div>
  `,
})
export class ZonaSoltar {
  readonly etiqueta = input('Arrastra tus archivos aquí');
  readonly ayuda = input('o haz clic para elegirlos');
  readonly acepta = input('.fit');
  readonly multiple = input(true);

  /**
   * Si trae texto, la zona está apagada y lo enseña en lugar de la ayuda.
   *
   * Un solo `input` y no una bandera más un mensaje aparte: apagar la zona sin
   * decir por qué es el mismo defecto que un botón muerto. El texto es el mismo
   * que enseña el botón de calcular, para que los dos cuenten lo mismo.
   */
  readonly esperando = input<string | null>(null);

  readonly archivos = output<File[]>();

  protected readonly encima = signal(false);

  /**
   * Los tres caminos de entrada comprueban `esperando` por su cuenta.
   *
   * El CSS ya corta el ratón con `pointer-events: none`, pero el teclado no
   * pasa por ahí y un foco puesto a mano seguiría abriendo el selector.
   */
  protected abrir(entrada: HTMLInputElement): void {
    if (!this.esperando()) entrada.click();
  }

  protected alArrastrar(evento: DragEvent): void {
    if (this.esperando()) return;
    evento.preventDefault();
    this.encima.set(true);
  }

  protected alSoltar(evento: DragEvent): void {
    if (this.esperando()) return;
    evento.preventDefault();
    this.encima.set(false);
    const lista = Array.from(evento.dataTransfer?.files ?? []);
    if (lista.length) this.archivos.emit(lista);
  }

  protected alElegir(evento: Event): void {
    const entrada = evento.target as HTMLInputElement;
    const lista = Array.from(entrada.files ?? []);
    if (lista.length && !this.esperando()) this.archivos.emit(lista);
    // Se limpia para que volver a elegir el mismo archivo dispare el evento.
    entrada.value = '';
  }
}
