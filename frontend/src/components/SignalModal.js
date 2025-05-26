import React from "react";

const SignalModal = ({ signal, onClose }) => (
  <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center">
    <div className="bg-white p-6 rounded shadow-lg">
      <h3 className="text-xl font-bold mb-2">Signal Details</h3>
      <pre className="mb-4">{JSON.stringify(signal, null, 2)}</pre>
      <button onClick={onClose} className="bg-blue-500 text-white p-2 rounded">
        Close
      </button>
    </div>
  </div>
);

export default SignalModal; 