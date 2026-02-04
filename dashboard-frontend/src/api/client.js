import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const fetchDashboardSummary = async () => {
  const response = await client.get('/api/dashboard/summary');
  return response.data;
};

export const fetchDashboardHistory = async (days = 30) => {
  const response = await client.get('/api/dashboard/history', {
    params: { days },
  });
  return response.data;
};

export const fetchSourceRankings = async () => {
  const response = await client.get('/api/dashboard/sources');
  return response.data;
};

export const fetchAffiliates = async () => {
  const response = await client.get('/api/affiliates');
  return response.data;
};

export const fetchBayesianBeliefs = async () => {
  const response = await client.get('/api/dashboard/beliefs');
  return response.data;
};

export const fetchSourceHistory = async (source, days = 30) => {
  const response = await client.get(`/api/dashboard/sources/${source}/history`, {
    params: { days },
  });
  return response.data;
};

export const fetchAllSourcesHistory = async (days = 30) => {
  const response = await client.get('/api/dashboard/sources/history/all', {
    params: { days },
  });
  return response.data;
};

export const fetchSourcesList = async () => {
  const response = await client.get('/api/dashboard/sources/list');
  return response.data;
};

export const fetchCoinsList = async () => {
  const response = await client.get('/api/dashboard/coins');
  return response.data;
};

export const fetchCoinPrice = async (coin) => {
  const response = await client.get(`/api/dashboard/coins/${coin}`);
  return response.data;
};

export const fetchCoinHistory = async (coin, days = 30) => {
  const response = await client.get(`/api/dashboard/coins/${coin}/history`, {
    params: { days },
  });
  return response.data;
};

export const fetchRecentPosts = async (limit = 20, source = null) => {
  const params = { limit };
  if (source) params.source = source;
  const response = await client.get('/api/dashboard/posts/recent', { params });
  return response.data;
};

export const fetchDailySentiment = async (days = 30, source = null) => {
  const params = { days };
  if (source) params.source = source;
  const response = await client.get('/api/dashboard/sentiment/daily', { params });
  return response.data;
};

export const fetchPanicScore = async () => {
  const response = await client.get('/api/dashboard/panic-score');
  return response.data;
};

export default client;
