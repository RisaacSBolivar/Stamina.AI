/**
 * La gráfica combinada: altimetría y ritmo sugerido, kilómetro a kilómetro.
 *
 * Es el elemento 🟢 imprescindible del diseño de solución. Dos detalles que no
 * son cosméticos:
 *
 * - El eje de ritmo va **invertido**. En min/km, menos es más rápido, así que
 *   sin invertir la curva se lee al revés de como la siente el corredor.
 * - La altimetría usa los 423 tramos de 100 m, no los 43 kilómetros. El perfil
 *   del terreno se aplana si se promedia por kilómetro.
 */
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { NgxEchartsDirective } from 'ngx-echarts';
import type { EChartsCoreOption } from 'echarts/core';

import type { FilaKm, PuntoAltimetria } from '../core/api.service';
import { duracion, ritmo } from '../core/formato';
import { TemaService } from '../core/tema.service';
import { COLOR_ZONA, colorDe } from '../core/zonas';

const MARCA = '#f36621';

/**
 * Los neutros de la grafica, por tema.
 *
 * Estan escritos aqui y no leidos de los tokens CSS porque ECharts pinta en un
 * canvas: no hay cascada que aplicar, hay que darle cada color hecho. Los
 * colores de zona no aparecen en esta tabla a proposito — son los mismos que uso
 * el notebook al graficar y no cambian con el tema.
 */
const NEUTROS = {
  claro: {
    tooltipFondo: '#ffffff',
    tooltipBorde: '#e2e6ec',
    texto: '#11223d',
    eje: '#c9d1dc',
    etiqueta: '#4a5a75',
    tenue: '#8b97a8',
    rejilla: '#eef1f5',
    relleno: 'rgba(139, 151, 168, 0.22)',
  },
  oscuro: {
    tooltipFondo: '#152238',
    tooltipBorde: '#2b3b58',
    texto: '#e7edf6',
    eje: '#3a4a66',
    etiqueta: '#aab8ce',
    tenue: '#7d8ca6',
    rejilla: '#1e2c46',
    relleno: 'rgba(125, 140, 166, 0.20)',
  },
};

@Component({
  selector: 'app-grafica-estrategia',
  imports: [NgxEchartsDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      echarts
      [options]="opciones()"
      [autoResize]="true"
      class="w-full"
      style="height: 420px"
      role="img"
      [attr.aria-label]="descripcion()"
    ></div>

    <div class="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs" style="color: var(--color-tinta-media)">
      @for (zona of zonasPresentes(); track zona) {
        <span class="inline-flex items-center">
          <span class="zona-punto" [style.background]="colorDe(zona)"></span>{{ zona }}
        </span>
      }
    </div>
  `,
})
export class GraficaEstrategia {
  readonly tablaKm = input.required<FilaKm[]>();
  readonly altimetria = input.required<PuntoAltimetria[]>();

  private tema = inject(TemaService);

  protected colorDe(zona: string): string {
    return colorDe(zona);
  }

  protected readonly zonasPresentes = computed(() => {
    const vistas = new Set(this.tablaKm().map((f) => f.zona));
    return Object.keys(COLOR_ZONA).filter((z) => vistas.has(z));
  });

  protected readonly descripcion = computed(() => {
    const filas = this.tablaKm();
    if (!filas.length) return 'Gráfica de la estrategia';
    const ritmos = filas.map((f) => f.ritmo_objetivo);
    return (
      `Altimetría y ritmo sugerido a lo largo de ${filas.length} kilómetros. ` +
      `Ritmo entre ${ritmo(Math.min(...ritmos))} y ${ritmo(Math.max(...ritmos))} por km.`
    );
  });

  /** Bandas de fondo por zona: bloques contiguos de la misma exigencia. */
  private readonly bandasZona = computed(() => {
    const filas = this.tablaKm();
    const bandas: { inicio: number; fin: number; zona: string }[] = [];

    for (const fila of filas) {
      const ultima = bandas.at(-1);
      if (ultima && ultima.zona === fila.zona) {
        ultima.fin = fila.km;
      } else {
        bandas.push({ inicio: fila.km - 1, fin: fila.km, zona: fila.zona });
      }
    }
    return bandas;
  });

  protected readonly opciones = computed<EChartsCoreOption>(() => {
    const filas = this.tablaKm();
    const perfil = this.altimetria();
    // Leer la señal aqui dentro basta para que la grafica se repinte al
    // cambiar de tema: `opciones` es un computed y ECharts recibe el objeto nuevo.
    const neutro = NEUTROS[this.tema.tema()];

    const ritmos = filas.map((f) => [f.km, f.ritmo_objetivo]);
    const elevacion = perfil.map((p) => [p.dist_km, p.elevacion]);
    const porKm = new Map(filas.map((f) => [f.km, f]));

    return {
      grid: { left: 58, right: 62, top: 28, bottom: 44 },
      animationDuration: 350,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'line' },
        backgroundColor: neutro.tooltipFondo,
        borderColor: neutro.tooltipBorde,
        textStyle: { color: neutro.texto, fontSize: 12 },
        formatter: (params: unknown) => {
          const lista = params as { axisValue: number }[];
          if (!lista?.length) return '';
          const km = Math.ceil(lista[0].axisValue);
          const fila = porKm.get(km);
          if (!fila) return `Km ${lista[0].axisValue.toFixed(1)}`;

          return [
            `<b>Km ${fila.km}</b>`,
            `Ritmo: <b>${ritmo(fila.ritmo_objetivo)} /km</b>`,
            `FC objetivo: ${Math.round(fila.fc_objetivo)} bpm`,
            `Elevación: ${Math.round(fila.elevacion)} m · pendiente ${fila.pendiente.toFixed(1)}%`,
            `Zona: <span style="color:${this.colorDe(fila.zona)}">&#9679;</span> ${fila.zona}`,
            `Acumulado: ${duracion(fila.tiempo_acum_min / 60)}`,
          ].join('<br/>');
        },
      },
      xAxis: {
        type: 'value',
        name: 'km',
        nameLocation: 'middle',
        nameGap: 26,
        min: 0,
        max: Math.ceil(filas.at(-1)?.km ?? 0),
        axisLine: { lineStyle: { color: neutro.eje } },
        axisLabel: { color: neutro.etiqueta },
        splitLine: { show: false },
      },
      yAxis: [
        {
          type: 'value',
          name: 'Elevación (m)',
          nameTextStyle: { color: neutro.tenue, fontSize: 11 },
          position: 'left',
          axisLabel: { color: neutro.tenue, fontSize: 11 },
          splitLine: { lineStyle: { color: neutro.rejilla } },
        },
        {
          type: 'value',
          name: 'Ritmo (/km)',
          nameTextStyle: { color: MARCA, fontSize: 11 },
          position: 'right',
          // Invertido: en min/km, menos es más rápido.
          inverse: true,
          // Sin esto ECharts incluye el cero y aplasta la curva contra el
          // borde: los ritmos viven en una banda estrecha (4-7 min/km) y lo
          // que importa es justo la variación dentro de esa banda.
          min: (valor: { min: number }) => Math.floor((valor.min - 0.15) * 10) / 10,
          max: (valor: { max: number }) => Math.ceil((valor.max + 0.15) * 10) / 10,
          axisLabel: {
            color: MARCA,
            fontSize: 11,
            formatter: (v: number) => ritmo(v),
          },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: 'Elevación',
          type: 'line',
          yAxisIndex: 0,
          data: elevacion,
          showSymbol: false,
          lineStyle: { width: 1, color: neutro.tenue },
          areaStyle: { color: neutro.relleno },
          z: 1,
          // Las bandas de zona van de fondo, no encima de la línea de ritmo.
          markArea: {
            silent: true,
            itemStyle: { opacity: 0.1 },
            data: this.bandasZona().map((banda) => [
              { xAxis: banda.inicio, itemStyle: { color: this.colorDe(banda.zona) } },
              { xAxis: banda.fin },
            ]),
          },
        },
        {
          name: 'Ritmo sugerido',
          type: 'line',
          yAxisIndex: 1,
          data: ritmos,
          showSymbol: false,
          smooth: 0.2,
          lineStyle: { width: 2.5, color: MARCA },
          z: 3,
        },
      ],
    };
  });
}
