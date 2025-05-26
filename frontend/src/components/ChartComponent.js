import React from "react";
import { Chart as ReactChart } from "react-chartjs-2";
import { Chart, registerables } from "chart.js";
import { FinancialController, CandlestickController, CandlestickElement } from "chartjs-chart-financial";
import annotationPlugin from "chartjs-plugin-annotation";

Chart.register(...registerables, FinancialController, CandlestickController, CandlestickElement, annotationPlugin);

const ChartComponent = ({ data, options, height = 350, movingAverage }) => {
  // Add moving average overlay if provided
  const chartData = { ...data };
  if (movingAverage && movingAverage.length) {
    chartData.datasets = [
      ...chartData.datasets,
      {
        label: "MA (20)",
        data: movingAverage,
        type: "line",
        borderColor: "#f59e42",
        borderWidth: 2,
        pointRadius: 0,
        fill: false,
        yAxisID: "y",
      },
    ];
  }
  return (
    <div style={{ height }}>
      <ReactChart type="candlestick" data={chartData} options={options} />
    </div>
  );
};

export default ChartComponent; 