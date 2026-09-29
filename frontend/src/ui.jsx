export function PageTitle({ title, subtitle }) {
  return (
    <div className="mb-6">
      <h2 className="font-serif text-2xl text-navy-900">{title}</h2>
      {subtitle && <p className="text-slate-500 mt-1 text-sm">{subtitle}</p>}
    </div>
  );
}

export function Card({ children, className = "" }) {
  return <div className={`bg-white rounded-xl border shadow-sm ${className}`}>{children}</div>;
}

export function Button({ children, onClick, type = "button", variant = "primary", disabled }) {
  const styles =
    variant === "primary"
      ? "bg-navy-800 text-white hover:bg-navy-700"
      : variant === "gold"
        ? "bg-gold-400 text-navy-900 hover:bg-gold-300"
        : "border text-slate-700 hover:bg-slate-50";
  return (
    <button type={type} disabled={disabled} onClick={onClick} className={`px-4 py-2 rounded-md text-sm font-medium disabled:opacity-50 ${styles}`}>
      {children}
    </button>
  );
}

export function Input({ label, ...props }) {
  return (
    <label className="block text-sm">
      <span className="text-slate-600">{label}</span>
      <input className="mt-1 w-full border rounded-md px-3 py-2" {...props} />
    </label>
  );
}

export function Select({ label, children, ...props }) {
  return (
    <label className="block text-sm">
      <span className="text-slate-600">{label}</span>
      <select className="mt-1 w-full border rounded-md px-3 py-2 bg-white" {...props}>
        {children}
      </select>
    </label>
  );
}

export function Table({ columns, rows, empty = "No records" }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50 text-left text-slate-500">
          <tr>
            {columns.map((c) => (
              <th key={c} className="px-4 py-2 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td className="px-4 py-8 text-center text-slate-400" colSpan={columns.length}>
                {empty}
              </td>
            </tr>
          )}
          {rows.map((row, i) => (
            <tr key={i} className="border-t">
              {row.map((cell, j) => (
                <td key={j} className="px-4 py-2 align-top">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ErrorBanner({ error }) {
  if (!error) return null;
  return <div className="mb-4 rounded-md bg-red-50 text-red-700 text-sm px-3 py-2">{error}</div>;
}

export function Badge({ children, tone = "slate" }) {
  const map = {
    green: "bg-emerald-50 text-emerald-700",
    amber: "bg-amber-50 text-amber-700",
    red: "bg-red-50 text-red-700",
    blue: "bg-sky-50 text-sky-800",
    slate: "bg-slate-100 text-slate-700",
  };
  return <span className={`text-xs px-2 py-1 rounded-full ${map[tone]}`}>{children}</span>;
}
