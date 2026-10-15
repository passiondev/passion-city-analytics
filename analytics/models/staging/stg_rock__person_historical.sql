with source as (

    select * from {{ source('rock', 'rock_analytics_dim_person_historical') }}

),

renamed as (

    select
        Id                                                  as person_historical_id,
        PersonId                                            as person_id,
        CurrentRowIndicator                                 as is_current_row,
        EffectiveDate                                       as effective_date,
        ExpireDate                                           as expire_date,

        PrimaryFamilyId                                     as primary_family_id,
        CampusId                                            as campus_id,
        CampusName                                          as campus_name,

        FirstName                                           as first_name,
        NickName                                            as nick_name,
        LastName                                            as last_name,

        GenderText                                          as gender,
        MaritalStatus                                       as marital_status,
        ConnectionStatus                                    as connection_status,
        RecordStatus                                        as record_status,
        RecordType                                          as record_type,
        cast(cast(IsDeceased as int64) as bool)             as is_deceased,

        Email                                               as email,
        EmailPreferenceText                                 as email_preference,

        -- giving / journey fields
        CurrentJourneyGivingStage                           as current_journey_giving_stage,
        PreviousJourneyGivingStage                          as previous_journey_giving_stage,
        JourneyGivingStageChangeDate                        as journey_giving_stage_change_date,
        GivingBin                                            as giving_bin,
        GivingPercentile                                    as giving_percentile,
        NextExpectedGiftDate                                as next_expected_gift_date,

        MailingAddressStreet1                               as mailing_address_street1,
        MailingAddressCity                                  as mailing_address_city,
        MailingAddressState                                 as mailing_address_state,
        MailingAddressPostalCode                            as mailing_address_postal_code,
        MailingAddressFull                                  as mailing_address_full,

        _loaded_at                                          as _bronze_loaded_at

    from source

)

select * from renamed
