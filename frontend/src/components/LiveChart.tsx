import { useEffect, useRef } from 'react';
import { createChart, AreaSeries } from 'lightweight-charts';
import type { IChartApi, ISeriesApi } from 'lightweight-charts';

interface LiveChartProps {
  data: { time: number; value: number }[];
  color?: string;
}

const dedupeAndSort = (data: { time: number; value: number }[]): { time: number; value: number }[] => {
  const asSeconds = data.map(d => ({
    time: Math.floor(d.time / 1000) as any,
    value: d.value,
  }));
  // Deduplicate: keep last occurrence for each timestamp
  const deduped: Record<number, { time: number; value: number }> = {};
  for (const item of asSeconds) deduped[item.time] = item;
  return Object.values(deduped).sort((a, b) => a.time - b.time);
};

export const LiveChart = ({ data, color = '#3b82f6' }: LiveChartProps) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 60,
      layout: {
        background: { color: 'transparent' },
        textColor: 'transparent',
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { visible: false },
      },
      handleScale: false,
      handleScroll: false,
      timeScale: { visible: false },
      rightPriceScale: { visible: false },
    });

    const areaSeries = chart.addSeries(AreaSeries, {
      lineColor: color,
      topColor: `${color}33`,
      bottomColor: 'transparent',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const formattedData = dedupeAndSort(data);
    if (formattedData.length > 0) {
      try { areaSeries.setData(formattedData); } catch (e) {
        console.warn('LiveChart init data error:', e);
      }
    }

    chartRef.current = chart;
    seriesRef.current = areaSeries;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync data updates without re-mounting
  useEffect(() => {
    if (!seriesRef.current || data.length === 0) return;
    const formattedData = dedupeAndSort(data);
    try { seriesRef.current.setData(formattedData); } catch (e) {
      console.warn('LiveChart update data error:', e);
    }
  }, [data]);

  return <div ref={chartContainerRef} className="w-full h-full" />;
};
