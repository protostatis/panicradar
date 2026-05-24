const VolatilityOutlook = ({ volatilityState, sentimentState }) => {
  const getMessage = () => {
    const isExtreme =
      sentimentState === 'Bullish' || sentimentState === 'Bearish';

    if (volatilityState === 'High' || volatilityState === 'Extreme') {
      return {
        title: 'High Volatility Detected',
        message: isExtreme
          ? 'Extreme sentiment combined with high volatility suggests potential for significant price moves.'
          : 'Elevated volatility detected. Consider position sizing carefully.',
        icon: '⚠️',
        borderColor: 'border-red-400/40',
      };
    }

    if (isExtreme) {
      return {
        title: 'Extreme Sentiment',
        message:
          sentimentState === 'Bullish'
            ? 'Strong bullish sentiment detected. Historically, extreme optimism can precede corrections.'
            : 'Strong bearish sentiment detected. Historically, extreme pessimism can mark bottoms.',
        icon: '📊',
        borderColor: 'border-yellow-400/40',
      };
    }

    return {
      title: 'Normal Conditions',
      message: 'Sentiment and volatility are within normal ranges.',
      icon: '✅',
      borderColor: 'border-slate-700/70',
    };
  };

  const { title, message, icon, borderColor } = getMessage();

  return (
    <div className={`radar-panel border ${borderColor} p-6`}>
      <h3 className="text-lg font-semibold text-slate-200 mb-2">
        {icon} {title}
      </h3>
      <p className="text-slate-400">{message}</p>
    </div>
  );
};

export default VolatilityOutlook;
