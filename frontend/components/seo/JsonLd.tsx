/**
 * SEO JSON-LD 组件
 *
 * 用于在页面中注入结构化数据，帮助搜索引擎理解页面内容
 *
 * 使用方式：
 * - 在页面中添加 <WebSiteJsonLd /> 组件以声明网站信息
 * - 在页面中添加 <OrganizationJsonLd /> 组件以声明组织信息
 */
interface JsonLdProps {
  data: Record<string, unknown>;
}

function JsonLd({ data }: JsonLdProps) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}

const BASE_URL = process.env.NEXT_PUBLIC_BASE_URL || "http://gitintel.top";

export function WebSiteJsonLd() {
  return (
    <JsonLd
      data={{
        "@context": "https://schema.org",
        "@type": "WebSite",
        name: "GitIntel AI Analysis",
        url: BASE_URL,
        description: "AI 驱动的 GitHub 仓库智能分析工具",
        publisher: {
          "@type": "Organization",
          name: "GitIntel",
          logo: {
            "@type": "ImageObject",
            url: `${BASE_URL}/favicon.ico`,
          },
        },
        potentialAction: {
          "@type": "SearchAction",
          target: {
            "@type": "EntryPoint",
            urlTemplate: `${BASE_URL}/?q={search_term_string}`,
          },
          "query-input": "required name=search_term_string",
        },
      }}
    />
  );
}

export function OrganizationJsonLd() {
  return (
    <JsonLd
      data={{
        "@context": "https://schema.org",
        "@type": "Organization",
        name: "GitIntel",
        url: BASE_URL,
        logo: `${BASE_URL}/favicon.ico`,
        sameAs: [
          "https://github.com/gitintel",
          "https://twitter.com/gitintel",
        ],
        contactPoint: {
          "@type": "ContactPoint",
          contactType: "customer support",
          email: "support@gitintel.ai",
        },
      }}
    />
  );
}

export function SoftwareApplicationJsonLd() {
  return (
    <JsonLd
      data={{
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        name: "GitIntel AI Analysis",
        applicationCategory: "DeveloperApplication",
        operatingSystem: "Web",
        url: BASE_URL,
        description:
          "利用 AI 技术对 GitHub 仓库进行深度架构分析、代码质量评估、依赖风险检测和优化建议。",
        offers: {
          "@type": "Offer",
          price: "0",
          priceCurrency: "USD",
          description: "基础版免费使用",
        },
        aggregateRating: {
          "@type": "AggregateRating",
          ratingValue: "4.8",
          ratingCount: "128",
        },
      }}
    />
  );
}

export default JsonLd;