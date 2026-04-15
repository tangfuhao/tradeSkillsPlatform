import { type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ChevronLeft } from 'lucide-react';

type PageHeaderProps = {
  eyebrow: string;
  title: string;
  description?: string;
  backTo?: string;
  backLabel?: string;
  actions?: ReactNode;
  status?: ReactNode;
};

export default function PageHeader({
  eyebrow,
  title,
  description,
  backTo,
  backLabel,
  actions,
  status,
}: PageHeaderProps) {
  return (
    <section className="page-header">
      <div className="page-header-lead">
        {backTo && (
          <Link className="page-header-back" to={backTo}>
            <ChevronLeft size={16} />
            {backLabel ?? '返回'}
          </Link>
        )}
        <p className="section-eyebrow">{eyebrow}</p>
        <h1 className="page-header-title">{title}</h1>
        {description && <p className="page-header-desc">{description}</p>}
        {status && <div className="page-header-status">{status}</div>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </section>
  );
}
