export const GA_EVENTS = {
  CTA_CLICK: 'cta_click',
  COIN_SELECT: 'coin_select',
  TIME_RANGE_CHANGE: 'time_range_change',
  BLOG_ARTICLE_CLICK: 'blog_article_click',
  TELEGRAM_CLICK: 'telegram_click',
  NEWSLETTER_CLICK: 'newsletter_click',
  SOURCE_VIEW: 'source_view',
  NEWS_VIEW: 'news_view',
  NEWS_CTA_CLICK: 'news_cta_click',
};

export function trackEvent(eventName, params = {}) {
  if (typeof window.gtag === 'function') {
    window.gtag('event', eventName, params);
  }
}
