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
        bgColor: 'bg-red-900/30',
        borderColor: 'border-red-500/50',
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
        bgColor: 'bg-yellow-900/30',
        borderColor: 'border-yellow-500/50',
      };
    }

    return {
      title: 'Normal Conditions',
      message: 'Sentiment and volatility are within normal ranges.',
      icon: '✅',
      bgColor: 'bg-slate-800/50',
      borderColor: 'border-slate-700',
    };
  };

  const { title, message, icon, bgColor, borderColor } = getMessage();

  return (
    <div className={`${bgColor} rounded-xl border ${borderColor} p-6`}>
      <h3 className="text-lg font-semibold text-slate-200 mb-2">
        {icon} {title}
      </h3>
      <p className="text-slate-400">{message}</p>
    </div>
  );
};

export default VolatilityOutlook;
