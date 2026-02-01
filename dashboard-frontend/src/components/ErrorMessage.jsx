const ErrorMessage = ({ message, onRetry }) => {
  return (
    <div className="bg-red-900/30 border border-red-500/50 rounded-xl p-6 text-center">
      <p className="text-red-400 mb-4">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  );
};

export default ErrorMessage;
