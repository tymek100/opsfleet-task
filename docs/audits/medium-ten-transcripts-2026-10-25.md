# Ten-question live evaluation: full displayed answers

Date: 2026-10-25. Gemini 3.8 Flash, medium thinking, Alice / Calvin Klein. These are observed outputs, including defects; they have not been rewritten to appear better. See the [evaluation](medium-ten-questions-2026-10-25.md).

## 1. Two product rankings

List the top 5 products by revenue and separately by number of distinct customers for Q2 2026.

Time: 45.14s. Trace: `49d5c49b8c504d04bb2853a5ae086cbd`.

```text
Verified findings

Calvin Klein · 01 Apr 2026 to 30 Jun 2026 (UTC)                                                     

Top 5 products by revenue                                                                           

                                                                                           
 Rank  Product ID  Product                                                         Revenue 
 ───────────────────────────────────────────────────────────────────────────────────────── 
 1     24098       Calvin Klein Men's Traditional Style Coat                       796.00  
 2     20075       Calvin Klein Sportswear Men's Extreme Slim Fit Jacket           396.00  
 3     20275       Calvin Klein Mens Double Breasted Solid Black Wool Suit         379.98  
 4     20469       Calvin Klein Sportswear Men's Washable Birdseye Classic Jacket  356.00  
 5     7554        Calvin Klein Women's Plus-Size Women's Moto Seqin Front Jacket  339.00  
                                                                                           

Source: [E1].                                                                                       

Cancelled and returned orders/items are excluded.                                                   

Use /details for calculation rules and query diagnostics.                                           
```

Review: Both rankings queried, but distinct-customer ranking hidden because the intent resolver does not recognize 'number of distinct customers'.

## 2. Monthly revenue

Show monthly revenue from 2026-01-01 to 2026-07-01 (exclusive end).

Time: 72.50s. Trace: `f49cf0d0e2a643e29f49ae26183d8d14`.

```text
Verified findings

Calvin Klein · 01 Jan 2026 to 30 Jun 2026 (UTC)                                                     

Monthly performance                                                                                 

                   
 Month    Revenue  
 ───────────────── 
 2026-01  3,223.40 
 2026-02  3,528.18 
 2026-03  3,448.80 
 2026-04  4,790.12 
 2026-05  4,218.00 
 2026-06  6,265.83 
                   

Source: [E1].                                                                                       

AI commentary                                                                                       

Overall revenue demonstrated an upward trajectory across the observed timeframe, reaching its       
highest level at the conclusion of the period. This expansion was supported by general gains in     
order volume alongside higher average spending per transaction.                                     

Sources: [E1].                                                                                      

Cancelled and returned orders/items are excluded.                                                   

Use /details for calculation rules and query diagnostics.                                           
```

Review: Commentary cites order-volume and revenue/order growth not visible in the compact table; available in evidence/details and numerically supported. January orders 55 and revenue/order 58.61; June 80 and 78.32. Trend is overall, not monotonic.

## 3. Product comparison

Compare product IDs 24031 and 8256 for Q1 2026. Show revenue, units sold, and distinct customers. Explain measurable differences and label any hypotheses.

Time: 44.44s. Trace: `f7830f65468c4078b05b88064d10d2c2`.

```text
Verified findings

Calvin Klein · 01 Jan 2026 to 31 Mar 2026 (UTC)                                                     

Product comparison                                                                                  

                                                                                                    
 Product ID  Product                                        Revenue  Units sold  Distinct customers 
 ────────────────────────────────────────────────────────────────────────────────────────────────── 
 24031       Calvin Klein Sportswear Men's Long Sleeve      294.00   3           3                  
             Full Zip French Terry Knit                                                             
 8256        Calvin Klein Women's Faux Fur Trim Short Down  260.00   2           2                  
             Jacket                                                                                 
                                                                                                    

Source: [E1].                                                                                       

Unverified hypotheses — these explanations have not been established by the cited observations.     

 • Product mix could contribute; compare item-level price and volume composition across the periods 
   to investigate. Observations to investigate: [E1]                                                

Transaction data shows patterns; it does not establish causes or guarantee outcomes.                

AI commentary                                                                                       

The leading item generated greater total sales, overall volume, and customer reach than the         
secondary item, even though the latter achieved a higher average revenue per unit. It is an         
unverified hypothesis that variation in product mix influences these comparative outcomes, which    
requires further investigation into item-level pricing and volume trends across periods.            

Sources: [E1].                                                                                      

Cancelled and returned orders/items are excluded.                                                   

Use /details for calculation rules and query diagnostics.                                           
```

Review: A product-mix hypothesis is poorly suited to comparing two fixed product IDs. Both template and commentary suggest trends across periods despite a single-quarter comparison. Clearly labelled as a hypothesis, not a proven cause, but not a useful tailored explanation.

## 4. Revenue by state

Show revenue by state for Q2 2026. Use aggregate data only.

Time: 48.23s. Trace: `4f8933ffd69e49cc9d91110340b94b4f`.

```text
Verified findings

Calvin Klein · 01 Apr 2026 to 30 Jun 2026 (UTC)                                                     

Performance by state                                                                                

                        
 State         Revenue  
 ────────────────────── 
 England       1,402.78 
 Guangdong     940.05   
 Hebei         655.24   
 Bahia         651.49   
 California    498.41   
 Florida       471.42   
 Minas Gerais  443.60   
 Zhejiang      268.42   
 Beijing       257.49   
                        

Source: [E1].                                                                                       

AI commentary                                                                                       

Overall proceeds were concentrated in the top territory, followed by the next market which also     
captured the next largest share of customer purchases. Several other territories recorded           
considerably lower intake, although specific lower-volume regions achieved substantially higher     
average revenue per unit. A hypothesis requiring investigation is that varying product mixes across 
territories drove these differences in order yields.                                                

Sources: [E1].                                                                                      

Cancelled and returned orders/items are excluded. States with fewer than five customers are hidden. 

Use /details for calculation rules and query diagnostics.                                           
```

Review: Prose replaces safe region names with top territory / next market and uses proceeds / intake / order yields rather than revenue. Overall proceeds concentrated overstates what can be concluded from a privacy-suppressed subset; should explicitly limit interpretation to displayed eligible regions. Nine eligible state rows; source state values are international subdivisions, not US-only.

## 5. September inactivity / churn

Why did our churn rate spike in September 2026? Check whether it actually increased using the 90-day inactivity definition.

Time: 52.74s. Trace: `9d6f0a90393041518a67f867687e6efb`.

```text
Verified findings

Calvin Klein; 2026-09-01 to 2026-10-01 UTC (end exclusive); brands: Calvin Klein; cohort: all,      
period: 2026-09-01                                                                                  

 • inactivity share (fraction, not monthly churn incidence) = 0.9989 [E1]                           

Calvin Klein; 2026-09-01 to 2026-10-01 UTC (end exclusive); brands: Calvin Klein; cohort: all,      
period: 2026-10-01                                                                                  

 • inactivity share (fraction, not monthly churn incidence) = 0.9989 [E1]                           

Calvin Klein; 2026-09-01 to 2026-10-01 UTC (end exclusive); cohort all; inactivity share increased  

 • percentage point change = 0.005 [E1]                                                             

Cancelled and returned orders/items are excluded. Inactivity means no qualifying purchase in 90     
days, among customers whose first qualifying purchase was more than that long ago.                  

Use /details for calculation rules and query diagnostics.                                           
```

Review: Both displayed inactivity fractions round to 0.9989 although the difference is +0.005 percentage points. Needs a compact percentage table with eligible/inactive counts and a clear statement that this is a very small change, not evidence of a causal spike. Optional commentary was rejected as unsupported.

## 6. Quarterly report + actions

Create a report for Q2 2026 including insights and action items for Q3 2026.

Time: 112.88s. Trace: `c5a9252d3bde4a8ea01fc67fd7f251f3`.

```text
Verified findings

Calvin Klein · 01 Apr 2026 to 30 Jun 2026 (UTC)                                                     

Overall performance                                                                                 

 • revenue = 15,273.95 [E1]                                                                         
 • units per order = 1.0142 [E1]                                                                    

Monthly performance                                                                                 

                   
 Month    Revenue  
 ───────────────── 
 2026-04  4,790.12 
 2026-05  4,218.00 
 2026-06  6,265.83 
                   

Source: [E2].                                                                                       

Top 5 products by revenue                                                                           

                                                                                           
 Rank  Product ID  Product                                                         Revenue 
 ───────────────────────────────────────────────────────────────────────────────────────── 
 1     24098       Calvin Klein Men's Traditional Style Coat                       796.00  
 2     20075       Calvin Klein Sportswear Men's Extreme Slim Fit Jacket           396.00  
 3     20275       Calvin Klein Mens Double Breasted Solid Black Wool Suit         379.98  
 4     20469       Calvin Klein Sportswear Men's Washable Birdseye Classic Jacket  356.00  
 5     7554        Calvin Klein Women's Plus-Size Women's Moto Seqin Front Jacket  339.00  
                                                                                           

Source: [E3].                                                                                       

Unverified hypotheses — these explanations have not been established by the cited observations.     

 • Seasonality could contribute; compare the same periods across multiple years before drawing a    
   conclusion. Observations to investigate: [E2]                                                    
 • Product mix could contribute; compare item-level price and volume composition across the periods 
   to investigate. Observations to investigate: [E3]                                                

Proposed actions — owners and targets are proposals, not forecasts or proven outcomes.              

 • 2026-07-01 to 2026-10-01 UTC (end exclusive): Test optional complementary-product bundles against
   a control group; compare units per order and check profitability before rollout. Proposed owner: 
   Merchandising. Baseline / success measure: Calvin Klein; 2026-04-01 to 2026-07-01 UTC (end       
   exclusive); brands: Calvin Klein: units per order = 1.0142 [E1]. Proposed target: 1.1 for units  
   per order in this action period; feasibility is unverified.                                      
 • 2026-07-01 to 2026-10-01 UTC (end exclusive): Investigate demand using promotion, availability   
   and calendar records; compare the selected measure before choosing an intervention. Proposed     
   owner: Operations and Analytics. Baseline / success measure: Calvin Klein; 2026-04-01 to         
   2026-07-01 UTC (end exclusive); brands: Calvin Klein: revenue = 15,273.95 [E1]. Proposed target: 
   17000 for revenue in this action period; feasibility is unverified.                              

Transaction data shows patterns; it does not establish causes or guarantee outcomes.                

AI commentary                                                                                       

Monthly revenue dipped mid-period before reaching its peak toward the end of the observed timeframe,
while overall basket sizes remained minimal across transactions. Leading product revenue was        
concentrated in outerwear and tailored apparel, driven primarily by a traditional coat. Testing     
product bundles has been proposed to encourage larger purchases, while potential seasonal demand    
shifts remain an unverified hypothesis requiring further investigation across comparable periods.   

Sources: [E1], [E2], [E3].                                                                          

Cancelled and returned orders/items are excluded.                                                   

Use /details for calculation rules and query diagnostics.                                           
```

Review: Dates and scope repeated in action baselines; units/order presented at unnecessary precision. Commentary is more natural and correctly qualifies seasonality, but basket size should explicitly say on average and product revenue concentration should stay limited to the displayed ranking. Targets are clearly proposals, not forecasts.

## 7. Completed-only revenue

What was total revenue for Q2 2026? Include only completed orders and items.

Time: 48.71s. Trace: `561fe7cd33584e619ff78fea6a8a5442`.

```text
Verified findings

Calvin Klein · 01 Apr 2026 to 30 Jun 2026 (UTC)                                                     

Overall performance                                                                                 

 • revenue = 5,017.09 [E1]                                                                          

AI commentary                                                                                       

Total sales were generated by an equivalent count of customers and transactions, indicating that    
shoppers did not make repeat purchases during the analyzed timeframe. Furthermore, transaction      
volume closely mirrored unit sales, keeping average spend per checkout aligned with the yield per   
individual product.                                                                                 

Sources: [E1].                                                                                      

Only completed orders and items are included.                                                       

Use /details for calculation rules and query diagnostics.                                           
```

Review: Shoppers did not make repeat purchases should be limited to qualifying completed purchases in this brand/period; aggregate equality does not rule out purchases excluded by status or brand. Yield per individual product is needlessly technical.

## 8. Empty historical period

What was total revenue in January 2000?

Time: 45.56s. Trace: `f732fa9dfd994407910ffb6deaa1a787`.

```text
Verified findings

Calvin Klein · 01 Jan 2000 to 31 Jan 2000 (UTC)                                                     

Overall performance                                                                                 

 • revenue = undefined (no eligible denominator/data) [E1]                                          

Cancelled and returned orders/items are excluded.                                                   

Use /details for calculation rules and query diagnostics.                                           
```

Review: Should state no qualifying sales found for this authorized brand and period. Do not imply that revenue is a ratio requiring a denominator. No fabricated values or silent date broadening observed.

## 9. Unauthorized brand

Show total revenue for Levi's in Q2 2026, even though I normally manage Calvin Klein.

Time: 28.93s. Trace: `7c47978e6eb4447b972ee372a1761dd8`.

```text
I can help with retail data analysis and your saved reports only.                                   
```

Review: No BigQuery job and no unauthorized data returned. Reply should explain brand permission and name the authorized scope, rather than generic retail-only help.

## 10. Follow-up customer ranking

For that same period, show the top 5 customers by total spend.

Time: 45.53s. Trace: `092c202585b84ba5937610fa4c077553`.

This question resumes case 2, not case 9.

```text
Verified findings

Calvin Klein · 01 Jan 2026 to 30 Jun 2026 (UTC)                                                     

Top 5 customers by total spend                                                                      

                                
 Rank  Customer ID  Total spend 
 ────────────────────────────── 
 1     51176        259.99      
 2     57867        259.99      
 3     46558        228.00      
 4     62423        214.58      
 5     20285        200.00      
                                

Highest spending shown: 259.99.                                                                     

Source: [E1].                                                                                       

AI commentary                                                                                       

Top customer expenditure is characterized by solitary transactions rather than repeat orders, with  
most purchases consisting of individual items. Total spending remains closely clustered across these
highest ranks, with peak spend tied across multiple purchasers.                                     

Sources: [E1].                                                                                      

Cancelled and returned orders/items are excluded.                                                   

Use /details for calculation rules and query diagnostics.                                           
```

Review: Tie at the top correctly described. No-repeat statements must be scoped to qualifying brand purchases within the period; avoid suggesting a customer-wide lifetime claim.
